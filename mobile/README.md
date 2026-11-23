# ClinicConnect patient app (Flutter)

Register, sign in, book / change / cancel visits, check in by scanning the clinic QR code, follow your queue
position live, read alerts and show your membership QR.

Needs Flutter 3.27 or newer. The backend must be running (`uvicorn app.main:app --reload` in `backend/`).

## First-time setup (once)

Run these in PowerShell from the project root (the folder that contains `backend/`). The order matters: create the
platform folders first, then the app code goes on top.

```powershell
mkdir mobile            # skip if it exists
cd mobile
flutter create --org com.clinicconnect --project-name clinicconnect --platforms=android,web,windows .
# now unzip the patient-app zip over this folder (see the chat for the command), then:
Remove-Item test\widget_test.dart -ErrorAction SilentlyContinue
python tools\setup_android.py      # camera + internet permissions, minSdk 23
flutter pub get
flutter analyze
flutter test
```

## Run

```powershell
flutter emulators --launch <id>     # or plug in a phone with USB debugging
flutter run
```

The app finds the API by itself: `10.0.2.2:8000` on the Android emulator (that is your PC), `localhost:8000` on
Windows / web. For a real phone on the same Wi-Fi use your PC's address:

```powershell
flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1
```

(Find it with `ipconfig`. Start uvicorn with `--host 0.0.0.0` so the phone can reach it.)

## Trying check-in

1. Sign in as staff in http://localhost:8000/docs and open `GET /branches/{id}/check-in-qr.png` to see the clinic QR.
   Show it on your PC screen and scan it with the phone. On the emulator or Windows (no camera) copy the token after
   `clinicconnect://checkin/` and paste it in the "clinic code" box instead.
2. You can only check in from 60 minutes before the slot until 30 minutes after it ends.

## Layout

```
lib/core/      config (API address), api_client (Dio, error text), session (login token, secure storage)
lib/models/    plain classes that read the API's JSON
lib/screens/   login, register, shell (tabs), home, book_* (clinic -> service -> day/time), appointments,
               appointment_detail, check_in, queue, notifications, profile
lib/widgets/   LoadView (spinner / error / retry), snackbars, status chips
```
