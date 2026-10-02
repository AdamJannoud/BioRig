// :core has no Android dependency, so everything in it runs as an ordinary JVM test.
plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.kotlin.serialization)
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    api(libs.h3)
    api(libs.okhttp)
    api(libs.kotlinx.serialization.json)
    api(libs.kotlinx.coroutines.core)
    api(libs.room.common)
    implementation(libs.bouncycastle)

    testImplementation(libs.junit)
    testImplementation(libs.okhttp.mockwebserver)
    testImplementation(libs.kotlinx.coroutines.test)
}

tasks.test {
    useJUnit()
    maxHeapSize = "512m"
    testLogging {
        events("passed", "failed", "skipped")
        exceptionFormat = org.gradle.api.tasks.testing.logging.TestExceptionFormat.FULL
        showStandardStreams = false
    }
}

// Prints the exact POST /v1/registrations body the app builds for a capture made now, for
// tools/check_registration_body.py to run through the relay's own relay/validate.py.
tasks.register<JavaExec>("emitRegistrationBody") {
    group = "verification"
    description = "Print the registration body :core builds, for the relay's validator"
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("org.biorig.core.relay.EmitRegistrationBodyKt")
}

// Drives SubmissionQueue against a live relay; tools/relay_e2e.py starts the real relay and passes its URL.
tasks.register<JavaExec>("relayE2e") {
    group = "verification"
    description = "Run the queue against a running relay (-Prelay=http://127.0.0.1:PORT)"
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("org.biorig.core.e2e.RelayE2eKt")
    args(providers.gradleProperty("relay").orElse("http://127.0.0.1:8787").get())
}
