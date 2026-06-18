import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [rfps, setRfps] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

  const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://52.207.113.238';

  useEffect(() => {
    fetchRfps();
  }, []);

  const fetchRfps = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/rfps`);
      setRfps(response.data);
    } catch (err) {
      setError('Failed to load RFPs. Make sure the backend is running.');
      console.error('Error fetching RFPs:', err);
    } finally {
      setLoading(false);
    }
  };

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
        <p>PLUR RFP Tracker • Backend: {API_BASE_URL}</p>
      </footer>
    </div>
  );
}

export default App;
