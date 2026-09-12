import Foundation
import Darwin

let root = Bundle.main.bundleURL
    .deletingLastPathComponent()
let python = root.appendingPathComponent(".native-venv/bin/python").path
let controller = root.appendingPathComponent("native/controller.py").path
let logPath = "/private/tmp/opengaze.log"
setenv("MPLCONFIGDIR", "/private/tmp/opengaze-mpl", 1)
setenv("XDG_CACHE_HOME", "/private/tmp/opengaze-cache", 1)
freopen(logPath, "a", stdout)
freopen(logPath, "a", stderr)
print("\n[OpenGaze] native process starting")
fflush(stdout)
let arguments = [python, controller]
let cArguments = arguments.map { strdup($0) } + [nil]
execv(python, cArguments)
perror("OpenGaze could not start")
exit(1)
