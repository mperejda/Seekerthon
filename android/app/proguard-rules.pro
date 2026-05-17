# Retrofit
-keepattributes Signature
-keepattributes *Annotation*
-keep class retrofit2.** { *; }
-keepclasseswithmembers class * {
    @retrofit2.http.* <methods>;
}

# Gson
-keep class com.google.gson.** { *; }
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# DTO / domain models
-keep class com.alpinelabs.seekerthon.data.remote.** { *; }
-keep class com.alpinelabs.seekerthon.domain.model.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
