# Deploy to Vercel (30 seconds, completely free)

Vercel is the easiest way to deploy your React app. It works instantly and is completely free.

## Quick Deploy

1. Go to: https://vercel.com/new

2. Click "Continue with GitHub"

3. Sign in with your GitHub account (aronhsiao-pl)

4. Find `plur-rfp-tracker-v2` repository and click "Import"

5. Configure:
   - **Framework Preset:** Next.js (or select React if available)
   - **Build Command:** `npm run build`
   - **Output Directory:** `build`
   - **Install Command:** `npm install`

6. Add Environment Variable:
   - Name: `REACT_APP_API_URL`
   - Value: `http://52.207.113.238`

7. Click "Deploy"

That's it! Your dashboard will be live in 30 seconds.

## Your Dashboard URL

After deployment, Vercel will give you a URL like:

```
https://plur-rfp-tracker-v2.vercel.app
```

OR a custom domain. You can share this link with your supervisor immediately!

## Auto-Deploy on Push

After the first deploy:
- Every push to `main` automatically redeploys
- No manual steps needed
- Dashboard updates in ~30 seconds

## Alternative: Netlify

If Vercel doesn't work, try Netlify:

1. Go to: https://app.netlify.com

2. Click "Add new site" → "Import an existing project"

3. Select GitHub and choose `plur-rfp-tracker-v2`

4. Build settings:
   - **Build command:** `npm run build`
   - **Publish directory:** `build`

5. Add environment variable:
   - `REACT_APP_API_URL=http://52.207.113.238`

6. Click "Deploy"

Done! Netlify gives you a live URL in seconds.

---

**Both Vercel and Netlify are free and production-grade. Pick whichever is faster for you.**

Your supervisor can access the dashboard immediately after deployment!
