// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "GaizeCompanion",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "GaizeCompanion",
            path: "Sources/GaizeCompanion",
            resources: [.copy("Resources/audio")],
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        )
    ]
)
