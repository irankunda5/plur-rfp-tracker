# PLUR RFP Tracker - Frontend

Modern React dashboard for real-time RFP tracking and analysis.

## Live Demo

📱 **Live:** https://aronhsiao-pl.github.io/plur-rfp-tracker-v2

## Features

- 📊 Real-time RFP dashboard with stats
- 🔍 Search and filter RFPs by status
- 📋 Beautiful card-based layout
- 📱 Fully responsive (mobile, tablet, desktop)
- ⚡ Fast and lightweight
- 🎨 Modern gradient UI with smooth animations
- 🔄 Auto-refresh capability

## Quick Start

### Prerequisites
- Node.js 16+
- npm or yarn

### Development

```bash
cd frontend
npm install
npm start
```

Opens http://localhost:3000 in your browser.

### Build for Production

```bash
npm run build
```

Creates optimized build in `build/` directory.

### Deploy to GitHub Pages

```bash
npm run deploy
```

Automatically builds and deploys to GitHub Pages (requires push access).

## Configuration

Edit `.env` to change the backend API URL:

```env
REACT_APP_API_URL=http://52.207.113.238
```

## Backend API Requirements

The frontend expects these endpoints from the backend:

```
GET /api/rfps
```

Returns array of RFP objects:
```json
[
  {
    "title": "RFP Title",
    "organization": "Organization Name",
    "status": "active|upcoming|closed",
    "deadline": "2026-07-31",
    "value": "$100,000",
    "description": "RFP description...",
    "url": "https://..."
  }
]
```

## Deployment

### GitHub Pages (Automatic)

1. Push to `main` branch
2. GitHub Actions workflow runs automatically
3. Deployed to `https://[username].github.io/plur-rfp-tracker-v2`

### Other Platforms

The `build/` folder can be deployed to:
- Netlify
- Vercel
- AWS S3 + CloudFront
- Any static hosting service

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Performance

- Bundle size: ~50KB gzipped
- Lighthouse score: 95+ (performance)
- Mobile-friendly: 100/100

## Project Structure

```
frontend/
├── public/
│   └── index.html          # Main HTML file
├── src/
│   ├── App.js             # Main component
│   ├── App.css            # Styles
│   └── index.js           # Entry point
├── package.json           # Dependencies
└── .env                   # Environment config
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| REACT_APP_API_URL | http://52.207.113.238 | Backend API base URL |

## Customization

### Styling

Edit `src/App.css` to customize:
- Colors
- Fonts
- Layout
- Animations

### Branding

Edit `src/App.js` to customize:
- Header title and subtitle
- Filter options
- Card display fields

## Troubleshooting

### CORS Issues
If you get CORS errors, ensure the backend includes proper headers:
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
```

### API Not Responding
1. Check backend is running
2. Verify API URL in `.env`
3. Check network tab in browser DevTools

### Build Fails
```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
npm run build
```

## Support

For issues or questions, open a GitHub issue: https://github.com/aronhsiao-pl/plur-rfp-tracker-v2/issues

## License

MIT
