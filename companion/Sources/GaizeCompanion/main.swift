import AppKit

@main
struct Main {
    @MainActor
    static func main() {
        setbuf(stdout, nil) // unbuffered, so redirected debug logs show up live

        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
