// BioRig Android: :core is plain Kotlin on the JVM, :app is the Compose application on top of it.
//
// :app is included only when an Android SDK can be found. The Android Gradle plugin refuses to configure a module
// without one, and Gradle configures every included project before it runs any task, so an unconditional
// include(":app") would make `./gradlew :core:test` fail on a machine that has a JDK and nothing else.
import java.util.Properties

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "biorig-android"

include(":core")

fun androidSdkDir(): File? {
    val local = File(settingsDir, "local.properties")
    val fromLocal = if (local.isFile) {
        Properties().apply { local.inputStream().use(::load) }.getProperty("sdk.dir")
    } else null
    return listOfNotNull(fromLocal, System.getenv("ANDROID_HOME"), System.getenv("ANDROID_SDK_ROOT"))
        .map(::File)
        .firstOrNull { File(it, "platforms").isDirectory }
}

val skipApp = providers.gradleProperty("biorig.skipApp").orNull == "true"
val sdk = androidSdkDir()
when {
    skipApp -> logger.lifecycle("biorig: :app left out (-Pbiorig.skipApp=true)")
    sdk == null -> logger.lifecycle(
        "biorig: no Android SDK found (local.properties sdk.dir, ANDROID_HOME, ANDROID_SDK_ROOT); " +
            ":app is left out of this build and :core builds on its own. See README.md.",
    )
    else -> include(":app")
}
