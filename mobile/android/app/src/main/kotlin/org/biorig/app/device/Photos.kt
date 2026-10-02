package org.biorig.app.device

import android.content.Context
import androidx.exifinterface.media.ExifInterface
import org.biorig.core.chain.Sha256
import org.biorig.core.geo.Fix
import org.biorig.core.photo.PhotoCheck
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

enum class PhotoKind(val label: String) { TRUNK("trunk"), CANOPY("canopy"), WIDE("wide") }

/** Photos stay in the app's private storage. Only the trunk photo's SHA-256 is sent, as `photo_sha256`. */
class PhotoStore(context: Context) {
    private val dir = File(context.filesDir, "photos").apply { mkdirs() }

    fun fileFor(captureKey: String, kind: PhotoKind): File = File(dir, "$captureKey-${kind.label}.jpg")

    fun digest(file: File): String = Sha256.hex(file)

    /** EXIF DateTimeOriginal is local wall time; the offset tag, when the camera wrote one, makes it absolute. */
    fun check(file: File, fix: Fix): PhotoCheck.Verdict {
        val exif = ExifInterface(file)
        val raw = exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL)
        val offset = exif.getAttribute(ExifInterface.TAG_OFFSET_TIME_ORIGINAL)
        val exifTime = raw?.let {
            val fmt = SimpleDateFormat("yyyy:MM:dd HH:mm:ss", Locale.US)
            fmt.timeZone = offset?.let { o -> TimeZone.getTimeZone("GMT$o") } ?: TimeZone.getDefault()
            runCatching { fmt.parse(it)?.time?.div(1000) }.getOrNull()
        }
        val latLng = exif.latLong
        return PhotoCheck.judge(fix, file.lastModified() / 1000, exifTime, latLng?.get(0), latLng?.get(1))
    }
}
