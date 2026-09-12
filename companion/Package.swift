// swift-tools-version:5.10
import PackageDescription

let package = Package(
    name: "GaizeCompanion",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(
            name: "GaizeCompanion",
            path: "Sources/GaizeCompanion",
            swiftSettings: [.unsafeFlags(["-parse-as-library"])]
        )
    ]
)
