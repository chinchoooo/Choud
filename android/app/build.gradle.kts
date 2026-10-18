import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Release signing. The key lives OUTSIDE the repository (default: ~/.personal-cloud-signing/,
// or the folder in $PC_SIGNING_DIR) and is never committed. Without it, a release build is
// simply left unsigned. KEEP A BACKUP of that folder: a phone only accepts an update that is
// signed with the same key as the installed app.
val signingProps = Properties().apply {
    val dir = System.getenv("PC_SIGNING_DIR") ?: "${System.getProperty("user.home")}/.personal-cloud-signing"
    val file = File(dir, "keystore.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "cloud.personal.sync"
    compileSdk = 34

    defaultConfig {
        applicationId = "cloud.personal.sync"
        minSdk = 26
        targetSdk = 34
        versionCode = 9
        versionName = "0.5.1"
    }

    signingConfigs {
        if (signingProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = File(signingProps.getProperty("storeFile"))
                storePassword = signingProps.getProperty("storePassword")
                keyAlias = signingProps.getProperty("keyAlias")
                keyPassword = signingProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("com.squareup.okhttp3:okhttp:5.5.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:5.5.0")
}
