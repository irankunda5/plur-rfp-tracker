# 🚀 Quick Start - Run Demo Now

## Fastest Way to See It Working (2 minutes)

### Step 1: Start the Application
```bash
cd plur-rfp-tracker-v2

# Option A: Direct Python (requires FastAPI installed)
python -m uvicorn web.app:app --reload --port 8081

# Option B: Docker (requires Docker)
docker-compose up

# Option C: Already on AWS?
# Application is already running at http://<ALB_DNS>/
```

### Step 2: Open in Browser

**Dashboard (Stats & Charts):**
```
http://localh
ost:8081/
```

**Search (Advanced Filtering):**
```
http://localhost:8081/search
```

---

## What You'll See

### Dashboard (`/`)
- 📊 Real-time statistics cards
- 📈 Interactive charts (bar + doughnut)
- 📋 Table of recent opportunities
- 🟢 Scraper status indicators
- ⚡ Auto-refresh every 5 minutes

### Search (`/search`)
- 🔍 Multi-filter search interface
- 🏷️ Filter by keywords, source, tier, date
- 📄 Card-based results display
- 📑 Pagination controls
- 🔗 Direct links to opportunities

---

## Demo Flow (5 minutes)

1. **Open Dashboard** (1 min)
   - Show stats: "1,255 opportunities"
   - Point to charts: "Distribution by source and tier"
   - Scroll to table: "Recent opportunities"

2. **Try Search** (2 min)
   - Search: "software"
   - Filter by Tier: "Tier 1"
   - Filter by Date: "Next 7 days"
   - Show results: Click on one to see source

3. **Show Features** (2 min)
   - Hover over cards (shadow effect)
   - Try pagination
   - Show mobile responsiveness
   - Mention AWS deployment

---

## Impressive Demo Talking Points

**"This is a live demo of our RFP aggregator..."**

- ✅ Tracks 1,255+ opportunities from 5 sources
- ✅ Real-time data updates throughout the day
- ✅ Smart filtering and prioritization
- ✅ Mobile responsive - works on any device
- ✅ Production-ready on AWS (automated deployment)
- ✅ Monitors: CanadaBuys, SAM.gov, Bonfire, SaskTenders, more

**"Key features:"**
- Dashboard for at-a-glance overview
- Advanced search with multiple filters
- Tier-based importance system (Tier 1-4)
- Closing date alerts (red = urgent)
- Automatic data collection from public sources

---

## If Something Goes Wrong

### Application won't start
```bash
# Check if port 8081 is in use
lsof -i :8081

# Kill the process
kill -9 <PID>

# Or use a different port
python -m uvicorn web.app:app --port 8082
```

### Database error
```bash
# Verify database exists
ls -la data/rfp.db

# Check if it has data
sqlite3 data/rfp.db "SELECT COUNT(*) FROM notices;"
```

### Charts not showing
- Refresh the page (Ctrl+R)
- Check browser console for errors (F12)
- Verify CDN is accessible (internet connection)

### No data in results
- Database may be empty (that's OK for demo)
- Show the search form and explain how it works
- Point to API documentation

---

## Quick API Tests

If you want to verify data is flowing:

```bash
# Check if API is responding
curl http://localhost:8081/api/health

# Get statistics
curl http://localhost:8081/api/stats

# Search for opportunities
curl "http://localhost:8081/api/search?page=1&per_page=5"
```

---

## Mobile Demo

To show mobile responsiveness:

1. Open in browser
2. Press F12 (Developer Tools)
3. Click device toggle (mobile icon)
4. Resize to different phone sizes
5. Show how layout adapts

---

## Screenshot Moments

Great for sharing later:

1. **Dashboard** - Full page view of stats and charts
2. **Search Results** - Show filtered results with pagination
3. **Mobile View** - Show responsive design
4. **Stats Cards** - Close-up of real-time statistics
5. **Charts** - Zoom in on visualizations

---

## Next Steps After Demo

**If they want to see it in production:**
→ Follow STEPS_TO_DEPLOY.md (35 minutes to AWS)

**If they want customization:**
→ Open DEMO_GUIDE.md (full customization guide)

**If they want the technical details:**
→ See DEPLOYMENT_SUMMARY.md (architecture overview)

---

## Deployment Info to Share

- ✅ **Fully Automated**: One command deploys to AWS
- ✅ **Production Grade**: RDS backups, monitoring, security
- ✅ **Cost Effective**: ~$97/month (can reduce to ~$50)
- ✅ **Scalable**: Auto-scaling ready
- ✅ **Monitored**: CloudWatch logs and alerts

---

## Key Files

- `web/templates/dashboard.html` - Dashboard page
- `web/templates/search.html` - Search page
- `web/app.py` - Backend (FastAPI)
- `DEMO_GUIDE.md` - Full demo guide
- `STEPS_TO_DEPLOY.md` - Production deployment

---

## Remember

The demo highlights:
1. **Modern UI** - Professional, clean design
2. **Real Data** - Live from public sources
3. **Easy to Use** - Intuitive interface
4. **Powerful** - Advanced filtering
5. **Production Ready** - Deployable to AWS

---

## One-Liner to Start

```bash
cd plur-rfp-tracker-v2 && python -m uvicorn web.app:app --reload --port 8081
```

Then open: **http://localhost:8081/**

---

**You're ready to impress! 🎉**

Start the app, open the browser, and walk through the 5-minute demo.
