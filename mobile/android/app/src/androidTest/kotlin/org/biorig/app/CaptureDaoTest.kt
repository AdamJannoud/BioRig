package org.biorig.app

// UNRUN IN THIS ENVIRONMENT. Instrumented test: needs a device or emulator (`./gradlew :app:connectedDebugAndroidTest`).
// The machine this was written on has no emulator, so this file was compiled at most, never executed.

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.test.runTest
import org.biorig.app.data.AppDatabase
import org.biorig.app.data.RoomCaptureStore
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureState
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CaptureDaoTest {
    private val db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), AppDatabase::class.java).build()
    private val store = RoomCaptureStore(db.captures())

    @After fun close() = db.close()

    @Test
    fun aCaptureKeepsItsSubmissionIdAcrossUpdates() = runTest {
        val c = CaptureEntity("abc", "0xD314e37FD8538fe66231EE670B74C9428d03feEa", 6.428093, 3.421974, 4.2,
            1_800_000_000, "unspecified", 10, null, null, 1_800_000_000)
        store.upsert(c)
        store.upsert(c.copy(state = CaptureState.SENT, jobId = "j"))
        val all = store.all()
        assertEquals(1, all.size)
        assertEquals("abc", all.single().submissionId)
        assertEquals(CaptureState.SENT, all.single().state)
    }
}
