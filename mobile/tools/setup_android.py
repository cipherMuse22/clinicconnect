"""Run once after `flutter create`: adds the permissions and settings the app needs on Android.

    python tools/setup_android.py
Safe to run again.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parent.parent / "android" / "app"
manifest = root / "src" / "main" / "AndroidManifest.xml"
if not manifest.exists():
    sys.exit("android/ folder not found. Run `flutter create` first (see mobile/README.md).")

text = manifest.read_text(encoding="utf-8")
perms = ['<uses-permission android:name="android.permission.INTERNET"/>',
         '<uses-permission android:name="android.permission.CAMERA"/>']
for perm in perms:
    if perm not in text:
        text = text.replace("<application", perm + "\n    <application", 1)
if "usesCleartextTraffic" not in text:  # lets the phone talk to http://10.0.2.2:8000 during development
    text = text.replace("<application", '<application android:usesCleartextTraffic="true"', 1)
manifest.write_text(text, encoding="utf-8")

for name in ("build.gradle.kts", "build.gradle"):
    g = root / name
    if g.exists():
        s = g.read_text(encoding="utf-8")
        s2 = re.sub(r"minSdk(Version)?(\s*=\s*|\s+)flutter\.minSdkVersion", lambda m: f"minSdk{m.group(1) or ''}{m.group(2)}23", s)
        if s2 != s:
            g.write_text(s2, encoding="utf-8")
        print(f"checked {name}")
print("Android setup done.")
