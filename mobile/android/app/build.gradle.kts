// :app — Compose UI, CameraX, fused location and the Room queue, on top of :core. Needs an Android SDK; see
// settings.gradle.kts for why it is only included when one is found.
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

// Where the app sends registrations and reads the chain. The relay default is the emulator's alias for the
// developer machine's loopback, where `python -m relay` listens on RELAY_PORT 8787. Override per build:
//   ./gradlew :app:assembleDebug -Pbiorig.relayUrl=https://relay.example.org
val relayUrl = providers.gradleProperty("biorig.relayUrl").orElse("http://10.0.2.2:8787").get()
// Celo mainnet (dashboard/chains.json, dashboard/deployment.json): public RPC and the BioRig proxy.
val rpcUrl = providers.gradleProperty("biorig.rpcUrl").orElse("https://forno.celo.org").get()
val proxyAddress = providers.gradleProperty("biorig.proxy").orElse("0x04db169ddf8abb80943161c01b2a71dc40384e64").get()

android {
    namespace = "org.biorig.app"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "org.biorig.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "RELAY_URL", "\"$relayUrl\"")
        buildConfigField("String", "RPC_URL", "\"$rpcUrl\"")
        buildConfigField("String", "PROXY_ADDRESS", "\"$proxyAddress\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // No signingConfig here on purpose: release signing material never lives in this repository.
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources.excludes += setOf(
            "META-INF/versions/9/OSGI-INF/MANIFEST.MF", "META-INF/{AL2.0,LGPL2.1}",
            // h3-java's desktop natives, carried as Java resources; the Android ones go in as jniLibs below
            "darwin-*/**", "windows-*/**", "linux-*/**", "android-*/**",
        )
    }
}

kotlin {
    jvmToolchain(17)
}

// com.uber:h3 ships its Android natives inside the jar as Java resources (android-arm64/, android-arm/), and AGP
// drops .so files from Java resources when it packages an APK. Without this task the APK has no libh3-java.so and
// H3Core cannot load on a phone. The libraries are copied into ABI directories and packaged as jniLibs; AppGraph
// loads them with H3Core.newSystemInstance(). h3-java has no x86/x86_64 Android build, so an x86_64 emulator image
// cannot run the H3 index: use an arm64 image or a device.
val h3Jar: Configuration by configurations.creating { isTransitive = false }
dependencies { h3Jar(libs.h3) }

abstract class ExtractH3Natives : DefaultTask() {
    @get:InputFiles abstract val jar: ConfigurableFileCollection
    @get:OutputDirectory abstract val outputDir: DirectoryProperty
    @get:Inject abstract val fs: FileSystemOperations
    @get:Inject abstract val archives: ArchiveOperations

    @TaskAction
    fun extract() {
        fs.sync {
            from(archives.zipTree(jar.singleFile)) {
                include("android-arm64/*.so", "android-arm/*.so")
                eachFile { path = path.replace("android-arm64/", "arm64-v8a/").replace("android-arm/", "armeabi-v7a/") }
            }
            includeEmptyDirs = false
            into(outputDir)
        }
    }
}

val extractH3Natives = tasks.register<ExtractH3Natives>("extractH3Natives") {
    jar.from(h3Jar)
    outputDir.set(layout.buildDirectory.dir("generated/h3-jniLibs"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.jniLibs?.addGeneratedSourceDirectory(extractH3Natives, ExtractH3Natives::outputDir)
    }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(project(":core"))

    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.activity.compose)
    implementation(libs.lifecycle.viewmodel.compose)
    implementation(libs.lifecycle.runtime.compose)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.play.services)

    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)

    implementation(libs.camerax.core)
    implementation(libs.camerax.camera2)
    implementation(libs.camerax.lifecycle)
    implementation(libs.camerax.view)
    implementation(libs.play.services.location)
    implementation(libs.exifinterface)

    androidTestImplementation(libs.androidx.test.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.rules)
    androidTestImplementation(libs.room.testing)
    androidTestImplementation(libs.kotlinx.coroutines.test)
    androidTestImplementation(platform(libs.compose.bom))
    androidTestImplementation(libs.compose.ui.test.junit4)
    debugImplementation(libs.compose.ui.test.manifest)
}
