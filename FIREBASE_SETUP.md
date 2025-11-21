# Firebase Admin SDK Setup Instructions

## Prerequisites
Firebase Admin SDK package is already installed.

## Setup Steps

### 1. Get Firebase Service Account Key

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project
3. Click the gear icon (⚙️) → Project Settings
4. Navigate to "Service Accounts" tab
5. Click "Generate New Private Key"
6. Save the downloaded JSON file

### 2. Add Service Account Key to Server

Move the downloaded JSON file to:
```
/home/lee/cloud_project/cloud-flask-server/serviceAccountKey.json
```

### 3. Add to .gitignore

Edit `/home/lee/cloud_project/cloud-flask-server/.gitignore` and add:
```
serviceAccountKey.json
```

### 4. Restart Server

Once the key is in place:
```bash
cd /home/lee/cloud_project/cloud-flask-server
# Stop current server (Ctrl+C)
python main.py
```

You should see:
```
✅ Firebase Admin initialized successfully
```

## Verification

After restarting:
1. Play a betting match
2. Complete the game
3. Check Firebase Console → Firestore
4. Verify money values updated correctly

## Current Status

- ✅ Firebase Admin package installed
- ✅ Configuration file created (`firebase_admin_config.py`)
- ✅ Firestore sync code added to payout functions
- ⏳ Service account key needed (follow steps above)

## Troubleshooting

**If you see:** `⚠️ Firebase Admin not available`
- Check serviceAccountKey.json exists
- Verify JSON format is valid
- Ensure file permissions are correct

**If money doesn't update:**
- Check server logs for Firestore errors
- Verify Firestore rules allow writes
- Confirm user UIDs match between Auth and Firestore
