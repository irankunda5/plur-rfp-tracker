# PLUR RFP Tracker - Demo Guide

## What's New

A modern, interactive frontend has been added for demo purposes with two main pages:

---

## 🎨 Dashboard (`/`)

Modern at-a-glance overview of the RFP tracking system.

### Features:
- **Real-time Stats**
  - Total opportunities in database
  - New opportunities this week
  - Active data sources
  - Last sync timestamp

- **Interactive Charts**
  - Bar chart: Opportunities by source (CanadaBuys, SAM.gov, Bonfire, SaskTenders)
  - Doughnut chart: Distribution by tier (Tier 1-4)
  - Live data from API

- **Recent Opportunities Table**
  - Title with direct links
  - Source badge
  - Buyer information
  - Closing date (highlighted if < 7 days)
  - Tier indicator
  - Sortable columns

- **Scraper Status**
  - 5 data sources with status indicators
  - Color-coded health status
  - Real-time updates

- **System Health Banner**
  - Shows overall system status
  - Pulsing indicator for online status

### Design:
- Modern gradient header (purple)
- Responsive grid layout
- Card-based components with hover effects
- Color-coded status indicators
- Mobile-friendly

---

## 🔍 Search Page (`/search`)

Advanced search interface for finding opportunities.

### Features:
- **Search Filters**
  - Keywords input
  - Source selector (CanadaBuys, SAM.gov, Bonfire, SaskTenders)
  - Tier filter (Tier 1-4)
  - Closing date filter (7, 30, 90 days)
  - Results per page (10, 25, 50, 100)

- **Results Display**
  - Card-based layout
  - Opportunity title with direct link
  - Full description preview
  - Source, buyer, closing date, tier
  - Matched keywords as tags
  - Direct "View" button

- **Pagination**
  - Previous/Next navigation
  - Page number selection
  - Smart pagination (shows ±2 pages from current)
  - Smooth scrolling

### Design:
- Clean search form at top
- Consistent with dashboard styling
- Real-time results
- Loading indicator

---

## 🚀 Live Demo

### Option 1: Run Locally (Fast)
```bash
cd plur-rfp-tracker-v2

# Start FastAPI development server
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8081

# Open browser
open http://localhost:8081
# or http://localhost:8081/search
```

### Option 2: Run with Docker
```bash
docker-compose up

# Open browser
open http://localhost:8081
```

### Option 3: AWS Deployment (Production)
Follow STEPS_TO_DEPLOY.md for full AWS deployment:
- Accessible via ALB DNS: `http://<ALB_DNS>/`
- Fully automated CI/CD
- Production monitoring

---

## 📋 Demo Walkthrough

### 1. Dashboard Overview (2 minutes)
1. Load `http://localhost:8081/`
2. Show real-time statistics
   - Point out total opportunities
   - Highlight new this week
   - Show last sync time
3. Scroll down to charts
   - Show distribution by source
   - Explain tier system
4. Scroll to recent opportunities
   - Click on a title to see source
   - Note closing dates (red = urgent)
5. Show scraper status
   - All 5 sources active
   - Status indicators working

### 2. Search & Filter (2 minutes)
1. Navigate to `/search`
2. Show default results (all opportunities)
3. Try filters:
   - Search for keyword: "software"
   - Filter by source: "CanadaBuys"
   - Filter by tier: "Tier 1"
   - Filter closing date: "Next 7 days"
4. Show pagination
   - Navigate between pages
   - Change results per page

### 3. Interactive Features (1 minute)
1. Click on opportunity titles
   - Opens source page in new tab
   - Shows live opportunity
2. Hover over cards
   - Show elevation/shadow effects
   - Demonstrate responsive design
3. Show auto-refresh
   - Dashboard updates every 5 minutes
   - Charts update automatically

---

## 🎯 Key Talking Points

### User Experience
- **Modern Design**: Clean, professional interface
- **Responsive**: Works on desktop, tablet, mobile
- **Intuitive Navigation**: Easy to find opportunities
- **Real-time Data**: Always up-to-date

### Technical Highlights
- **FastAPI Backend**: High-performance Python framework
- **Tailwind CSS**: Modern responsive styling
- **Chart.js**: Beautiful data visualization
- **Zero Dependencies**: Uses CDN-hosted libraries (no npm build)

### Business Value
- **Centralized Hub**: Single source for all procurement opportunities
- **Smart Filtering**: Find exactly what you're looking for
- **Status Tracking**: Know which sources are active
- **Tier System**: Prioritize by importance

---

## 🔄 API Endpoints (For Developers)

Used by the frontend:

```bash
# Dashboard stats
GET /api/stats
# Response: {
#   "total": 1255,
#   "new_this_week": 42,
#   "sources": 5,
#   "last_sync": "2024-06-17T14:30:00Z"
# }

# Health check
GET /api/health
# Response: {
#   "status": "healthy",
#   "runs": [...last 50 scraper runs...]
# }

# Search opportunities
GET /api/search?q=software&source=canadabuys&tier=1&page=1&per_page=25
# Response: {
#   "total": 156,
#   "page": 1,
#   "per_page": 25,
#   "total_pages": 7,
#   "items": [...]
# }
```

---

## 🛠️ Development

### File Structure
```
web/
├── app.py              # FastAPI application
│                       # - GET / → Dashboard
│                       # - GET /search → Search page
│                       # - GET /api/health → Health check
│                       # - GET /api/stats → Dashboard stats
│                       # - GET /api/search → Search results
│
└── templates/
    ├── dashboard.html  # Modern dashboard (new)
    ├── search.html     # Search page (new)
    ├── base.html       # Base template (existing)
    ├── index.html      # Original index (existing)
    ├── detail.html     # Details page (existing)
    ├── health.html     # Health check (existing)
    └── renewals.html   # Renewals page (existing)
```

### To Customize Dashboard
Edit `web/templates/dashboard.html`:
- **Colors**: Change gradient-bg colors (line ~15)
- **Stats**: Add more metrics to stats grid
- **Charts**: Modify chart.js config for different visualizations
- **Layout**: Adjust Tailwind grid columns

### To Customize Search
Edit `web/templates/search.html`:
- **Filters**: Add more filter options
- **Results**: Modify card layout
- **Pagination**: Adjust page window size

---

## 🐛 Troubleshooting

### Dashboard not loading
```bash
# Check API is responding
curl http://localhost:8081/api/stats

# Check database is accessible
sqlite3 data/rfp.db "SELECT COUNT(*) FROM notices;"
```

### Charts not showing
- Check browser console for JavaScript errors
- Verify API is returning data with correct format
- Check Chart.js CDN is accessible

### Search returning no results
- Verify database has data
- Check filter values match actual data
- Try with empty search first

### Styling looks broken
- Clear browser cache (Ctrl+Shift+Delete)
- Check Tailwind CSS CDN is loading
- Verify no content security policy blocking CDN

---

## 📸 Demo Screenshots

### Dashboard
- Header: "PLUR RFP Tracker" with purple gradient
- 4 stat cards with icons
- 2 charts side by side
- Table of recent opportunities
- 5 scraper status indicators

### Search
- Search form with 5 filter inputs
- Loading spinner while searching
- Results as cards with full info
- Pagination controls
- Navigation links back to dashboard

---

## ✨ Features Showcase

### What Makes It Demo-Ready

1. **Visual Appeal**
   - Modern design with gradients
   - Smooth animations
   - Professional color scheme
   - Responsive on all devices

2. **Interactivity**
   - Real-time stats
   - Live search results
   - Interactive charts
   - Working pagination

3. **Information Density**
   - At-a-glance stats on dashboard
   - Detailed search capabilities
   - Multiple data sources
   - Status tracking

4. **Performance**
   - Fast page loads (no build step)
   - Efficient API calls
   - Optimized CDN resources
   - Responsive interactions

---

## 🎬 Demo Script (5 minutes)

**Opening (30 seconds)**
- "This is PLUR RFP Tracker - a public procurement opportunity aggregator"
- "It monitors 5 major sources: CanadaBuys, SAM.gov, Bonfire, SaskTenders, and more"

**Dashboard (2 minutes)**
- "The dashboard gives you an at-a-glance view of what's happening"
- Point to stats: "1,255 opportunities tracked, 42 new this week"
- Show charts: "You can see which sources have the most opportunities"
- Table: "These are the most recent opportunities, sorted by closing date"

**Search (2 minutes)**
- "Need to find something specific? Use the search page"
- "You can filter by keywords, source, priority tier, and closing date"
- "Let's find all Tier 1 opportunities closing in the next 7 days"
- Show results: "Here are your matches, sorted by relevance"

**Closing (30 seconds)**
- "The whole system runs on AWS with automated backups"
- "New data is fetched automatically throughout the day"
- "You get notifications when new opportunities match your criteria"

---

## 🚀 Next Steps

After the demo:

1. **Deploy to Production**
   - Follow STEPS_TO_DEPLOY.md
   - Takes ~35 minutes
   - Full AWS infrastructure

2. **Customize for Your Needs**
   - Add your company logo
   - Customize color scheme
   - Add additional filters
   - Integrate with your systems

3. **Set Up Automation**
   - Email digests
   - Slack notifications
   - Calendar integration
   - CRM sync (HubSpot)

4. **Scale Up**
   - Add more data sources
   - Implement AI matching
   - Add user accounts
   - Build export features

---

## 📞 Support

- **Frontend Issues**: Check browser console for errors
- **API Issues**: Check `/api/health` endpoint
- **Data Issues**: Check database in `data/rfp.db`
- **Deployment Issues**: Follow STEPS_TO_DEPLOY.md

---

**Ready to demo!** 🎉

Start with: `http://localhost:8081/`
