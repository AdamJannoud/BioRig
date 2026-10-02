// Every plugin is put on the root classpath once, unapplied, so the Kotlin plugin and the Android plugin share one
// classloader. Resolving a plugin needs only the repositories, not an Android SDK: the SDK check happens when AGP
// is applied, which only :app does, and :app is only included when an SDK is found (settings.gradle.kts).
plugins {
    alias(libs.plugins.kotlin.jvm) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.android.application) apply false
}
