package org.biorig.app.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow
import org.biorig.core.queue.CaptureEntity
import org.biorig.core.queue.CaptureStore
import org.biorig.core.queue.Session
import org.biorig.core.queue.SessionStore
import org.biorig.core.relay.InstallIdStore

@Dao
interface CaptureDao {
    @Upsert
    suspend fun upsert(capture: CaptureEntity)

    @Query("SELECT * FROM captures WHERE submissionId = :id")
    suspend fun get(id: String): CaptureEntity?

    @Query("SELECT * FROM captures ORDER BY createdAt")
    suspend fun all(): List<CaptureEntity>

    @Query("SELECT * FROM captures ORDER BY createdAt DESC")
    fun observeAll(): Flow<List<CaptureEntity>>
}

/** The queue lives in the phone's database, not in memory: closing the app loses nothing. */
@Database(entities = [CaptureEntity::class], version = 1, exportSchema = true)
abstract class AppDatabase : RoomDatabase() {
    abstract fun captures(): CaptureDao

    companion object {
        fun open(context: Context): AppDatabase =
            Room.databaseBuilder(context, AppDatabase::class.java, "biorig.db").build()
    }
}

class RoomCaptureStore(private val dao: CaptureDao) : CaptureStore {
    override suspend fun upsert(capture: CaptureEntity) = dao.upsert(capture)
    override suspend fun get(submissionId: String) = dao.get(submissionId)
    override suspend fun all() = dao.all()
}

/**
 * Plain preferences: the planter's PUBLIC address, the relay session token and the install id. The token is a
 * rate-limit key that expires in 24 h and the install id a random rate-limit key that never does; neither is a
 * credential to anything, and there is no private key, mnemonic or keystore in this app.
 */
class Prefs(context: Context) : SessionStore, InstallIdStore {
    private val sp = context.getSharedPreferences("biorig", Context.MODE_PRIVATE)

    var planterAddress: String?
        get() = sp.getString("planter_address", null)
        set(value) = sp.edit().putString("planter_address", value).apply()

    override fun loadInstallId(): String? = sp.getString("install_id", null)

    // commit, not apply: the id is written once, and it must be on disk before the first request carries it.
    override fun saveInstallId(id: String) {
        sp.edit().putString("install_id", id).commit()
    }

    override suspend fun load(): Session? {
        val token = sp.getString("session_token", null) ?: return null
        return Session(token, sp.getLong("session_expires_at", 0))
    }

    override suspend fun save(session: Session?) {
        sp.edit().apply {
            if (session == null) remove("session_token").remove("session_expires_at")
            else putString("session_token", session.token).putLong("session_expires_at", session.expiresAt)
        }.apply()
    }
}
