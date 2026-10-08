package org.biorig.app.ui

import android.location.Location
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import org.biorig.core.geo.Fix
import java.io.File

/** CameraX preview plus one capture button. The fix is written into the photo's EXIF so the check can compare. */
@Composable
fun CameraCapture(label: String, fix: Fix, target: () -> File, onSaved: (File) -> Unit, onError: (String) -> Unit) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val capture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build() }
    val previewView = remember { PreviewView(context) }

    DisposableEffect(owner) {
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = future.get()
            val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
            provider.unbindAll()
            provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
        }, ContextCompat.getMainExecutor(context))
        onDispose { runCatching { future.get().unbindAll() } }
    }

    Column {
        AndroidView({ previewView }, Modifier.fillMaxWidth().padding(top = 8.dp).height(260.dp).clip(RoundedCornerShape(14.dp)))
        Primary("Photograph the $label") {
            val file = target()
            val metadata = ImageCapture.Metadata().apply {
                location = Location("fix").apply { latitude = fix.lat; longitude = fix.lng }
            }
            val options = ImageCapture.OutputFileOptions.Builder(file).setMetadata(metadata).build()
            capture.takePicture(options, ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageSavedCallback {
                    override fun onImageSaved(output: ImageCapture.OutputFileResults) = onSaved(file)
                    override fun onError(exception: ImageCaptureException) = onError(exception.message ?: "camera error")
                })
        }
    }
}
