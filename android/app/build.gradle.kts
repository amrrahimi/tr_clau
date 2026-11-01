plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "ir.amrrahimi.tradingbot"
    compileSdk = 35

    defaultConfig {
        applicationId = "ir.amrrahimi.tradingbot"
        minSdk = 26
        targetSdk = 35
        // Every build gets a higher number, so a new APK installs over the old one (data is kept).
        versionCode = (System.getenv("GITHUB_RUN_NUMBER") ?: "1").toInt()
        versionName = "0.2.${System.getenv("GITHUB_RUN_NUMBER") ?: "0"}"
        ndk {
            abiFilters += listOf("arm64-v8a")   // practically every phone of the last years
        }
    }

    // One fixed key (kept in the repository's secrets), so each new version installs as an update.
    signingConfigs {
        create("release") {
            val keystore = System.getenv("ANDROID_KEYSTORE")
            if (keystore != null) {
                storeFile = file(keystore)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("ANDROID_KEYSTORE") != null)
                signingConfigs.getByName("release") else signingConfigs.getByName("debug")
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

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            install("-r", "requirements-android.txt")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.12.1")
}
