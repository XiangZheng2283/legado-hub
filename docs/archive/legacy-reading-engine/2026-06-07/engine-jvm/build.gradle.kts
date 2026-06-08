import org.gradle.api.file.DuplicatesStrategy

plugins {
    kotlin("jvm")
    kotlin("plugin.serialization")
    application
}

group = "legadohub"
version = "0.0.1"

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jsoup:jsoup:1.18.3")
    implementation("com.jayway.jsonpath:json-path:2.9.0")
    implementation("org.mozilla:rhino:1.7.15")
    implementation("com.google.code.gson:gson:2.11.0")
    implementation("com.github.liuyueyi.quick-chinese-transfer:quick-transfer-core:0.2.17")

    testImplementation("io.kotest:kotest-runner-junit5:5.9.1")
    testImplementation("io.kotest:kotest-assertions-core:5.9.1")
}

application {
    mainClass.set("legadohub.engine.bridge.EngineCliKt")
}

tasks.jar {
    manifest {
        attributes["Main-Class"] = "legadohub.engine.bridge.EngineCliKt"
    }
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    from(configurations.runtimeClasspath.get().map { dependency ->
        if (dependency.isDirectory) dependency else zipTree(dependency)
    })
}

tasks.test {
    useJUnitPlatform()
}
