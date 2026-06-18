# Deploy Frontend Right Now (2 minutes)

This gets your dashboard live and shareable.

## One-Time Setup

```bash
cd frontend
npm install
```

Wait ~30 seconds while it installs React and dependencies.

## Deploy to GitHub Pages

```bash
npm run deploy
```

This will:
1. Build your React app
2. Optimize the code
3. Push to GitHub Pages
4. Done!

## View Your Dashboard

**Live:** https://aronhsiao-pl.github.io/plur-rfp-tracker-v2

It's live immediately. Share this link with your supervisor!

## If Something Goes Wrong

### Error: "command not found: npm"

Install Node.js: https://nodejs.org/
Then try again.

### Error: "ENOTFOUND api.github.com"

You might not have git credentials setup. Try:
```bash
git config --global user.email "your@email.com"
git config --global user.name "Your Name"
npm run deploy
```

### Dashboard shows "Failed to load RFPs"

This is OK for now—the backend is probably still initializing (up to 5 minutes).

Wait 2 minutes, then refresh the page.

### Dashboard loads but no data

Backend endpoint not ready yet. Check:
```bash
curl http://52.207.113.238/api/rfps
```

---

## That's It!

Your dashboard is live and shareable. Future updates automatically deploy when you push to `main`.

**Share this:** https://aronhsiao-pl.github.io/plur-rfp-tracker-v2
