plugins {
    kotlin("jvm") version "1.9.20"
}

dependencies {
    implementation("io.ktor:ktor-server-core:2.3.5")
    implementation("ch.qos.logback:logback-classic:1.4.14")
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.0")
    kapt("com.google.dagger:dagger-compiler:2.48")
}
