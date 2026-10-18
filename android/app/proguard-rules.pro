# OkHttp / Okio ship their own consumer rules; these silence the optional platform classes they probe for.
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**

# Tink (used by EncryptedSharedPreferences) references annotation-only classes.
-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn com.google.api.client.**
-dontwarn org.joda.time.**

# Our SQLite helpers and Activities are referenced from the manifest; AGP keeps those. Keep line numbers for crash reports.
-keepattributes SourceFile,LineNumberTable
