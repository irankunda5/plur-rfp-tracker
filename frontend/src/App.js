import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import './App.css';

const DEMO_DATA = [
  {
    title: "Federal IT Infrastructure Modernization RFP",
    organization: "Department of Defense",
    status: "active",
    deadline: "2026-08-15",
    value: "$50,000,000",
    description: "Seeking qualified contractors for comprehensive IT infrastructure modernization including cloud migration, cybersecurity enhancements, and legacy system replacement.",
    url: "https://www.fbo.gov/"
  },
  {
    title: "Healthcare Data Analytics Platform",
    organization: "Centers for Medicare & Medicaid Services",
    status: "active",
    deadline: "2026-07-30",
    value: "$15,000,000",
    description: "Request for proposals to develop and implement an advanced data analytics platform for healthcare cost and quality measurement.",
    url: "https://www.fbo.gov/"
  },
  {
    title: "Cybersecurity Framework Implementation",
    organization: "National Institute of Standards and Technology",
    status: "upcoming",
    deadline: "2026-09-15",
    value: "$5,000,000",
    description: "RFP for implementation of updated NIST cybersecurity framework across federal agencies.",
    url: "https://www.fbo.gov/"
  },
  {
    title: "Legacy System Migration Project",
    organization: "Social Security Administration",
    status: "closed",
    deadline: "2026-06-30",
    value: "$25,000,000",
    description: "Closed RFP for migration of legacy mainframe systems to modern cloud infrastructure. Winner announced.",
    url: "https://www.fbo.gov/"
  }
];

function App() {
  const [rfps, setRfps] = useState(DEMO_DATA);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [useBackend, setUseBackend] = useState(true);
  const [backendStatus, setBackendStatus] = useState('checking');

  const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://52.207.113.238';

  const checkBackendHealth = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/health`, { timeout: 5000 });
      setBackendStatus('online');
      return true;
    } catch (err) {
      setBackendStatus('offline');
      console.warn('Backend offline, using demo data');
      return false;
    }
  }, [API_BASE_URL]);

  const fetchRfps = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      if (useBackend) {
        const response = await axios.get(`${API_BASE_URL}/api/rfps`, { timeout: 5000 });
        setRfps(response.data);
        setError(null);
      } else {
        setRfps(DEMO_DATA);
      }
    } catch (err) {
      console.error('Error fetching RFPs:', err);
      setRfps(DEMO_DATA);
      if (useBackend) {
        setError('Backend unavailable - showing demo data');
        setBackendStatus('offline');
      }
    } finally {
      setLoading(false);
    }
  }, [API_BASE_URL, useBackend]);

  useEffect(() => {
    checkBackendHealth();
  }, [checkBackendHealth]);

  useEffect(() => {
    fetchRfps();
  }, [fetchRfps]);

  const filteredRfps = rfps.filter(rfp => {
    const matchesFilter = filter === 'all' || rfp.status === filter;
    const matchesSearch = !searchTerm ||
      rfp.title?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rfp.organization?.toLowerCase().includes(searchTerm.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const stats = {
    total: rfps.length,
    active: rfps.filter(r => r.status === 'active').length,
    closed: rfps.filter(r => r.status === 'closed').length,
    upcoming: rfps.filter(r => r.status === 'upcoming').length,
  };

  return (
    <div className="app">
      <header className="header">
        <div className="header-content">
          <h1>PLUR RFP Tracker</h1>
          <p>Real-time RFP tracking and analysis</p>
        </div>
        <div className="backend-status">
          <span className={`status-indicator ${backendStatus}`}></span>
          <span className="status-text">{backendStatus === 'checking' ? 'Checking...' : `Backend: ${backendStatus}`}</span>
        </div>
      </header>

      <main className="main">
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.total}</div>
            <div className="stat-label">Total RFPs</div>
          </div>
          <div className="stat-card active">
            <div className="stat-value">{stats.active}</div>
            <div className="stat-label">Active</div>
          </div>
          <div className="stat-card upcoming">
            <div className="stat-value">{stats.upcoming}</div>
            <div className="stat-label">Upcoming</div>
          </div>
          <div className="stat-card closed">
            <div className="stat-value">{stats.closed}</div>
            <div className="stat-label">Closed</div>
          </div>
        </div>

        <div className="controls">
          <input
            type="text"
            placeholder="Search RFPs..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="search-input"
          />
          <div className="filter-buttons">
            {['all', 'active', 'upcoming', 'closed'].map(f => (
              <button
                key={f}
                className={`filter-btn ${filter === f ? 'active' : ''}`}
                onClick={() => setFilter(f)}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          <button className="refresh-btn" onClick={fetchRfps} disabled={loading}>
            {loading ? 'Loading...' : 'Refresh'}
          </button>
          <button
            className={`mode-btn ${useBackend ? 'backend' : 'demo'}`}
            onClick={() => setUseBackend(!useBackend)}
            title={useBackend ? 'Click to use demo data' : 'Click to use backend'}
          >
            {useBackend ? 'Backend Mode' : 'Demo Mode'}
          </button>
        </div>

        {error && <div className="error-message">{error}</div>}

        <div className="rfps-container">
          {filteredRfps.length === 0 ? (
            <div className="empty-state">
              <p>No RFPs found</p>
            </div>
          ) : (
            filteredRfps.map((rfp, idx) => (
              <div key={idx} className={`rfp-card status-${rfp.status || 'unknown'}`}>
                <div className="rfp-header">
                  <h3>{rfp.title}</h3>
                  <span className={`status-badge ${rfp.status || 'unknown'}`}>
                    {(rfp.status || 'unknown').toUpperCase()}
                  </span>
                </div>
                <div className="rfp-body">
                  <p><strong>Organization:</strong> {rfp.organization || 'N/A'}</p>
                  {rfp.deadline && <p><strong>Deadline:</strong> {rfp.deadline}</p>}
                  {rfp.value && <p><strong>Value:</strong> {rfp.value}</p>}
                  {rfp.description && (
                    <p><strong>Description:</strong> {rfp.description.substring(0, 150)}...</p>
                  )}
                </div>
                {rfp.url && (
                  <div className="rfp-footer">
                    <a href={rfp.url} target="_blank" rel="noopener noreferrer" className="view-link">
                      View Full RFP →
                    </a>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </main>

      <footer className="footer">
        <p>PLUR RFP Tracker • Data Source: {useBackend ? API_BASE_URL : 'Demo'}</p>
      </footer>
    </div>
  );
}

export default App;
