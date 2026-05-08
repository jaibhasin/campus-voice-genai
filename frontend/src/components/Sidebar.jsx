"use client";

export default function Sidebar({ onQuickQuestion, onNewConversation }) {
  const quickQuestions = [
    "What is the B.Tech fee structure?",
    "How do I apply for admission?",
    "What scholarships are available?",
    "Tell me about international exchange programs",
    "What are the hostel charges?",
  ];

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <span className="emoji">🎓</span>
        <h2>Scout</h2>
      </div>
      <div className="glow-divider" />

      {/* Status */}
      <span className="status-badge">● Online</span>

      {/* Description */}
      <p className="sidebar-description">
        Your AI assistant for{" "}
        <strong>Thapar Institute of Engineering &amp; Technology</strong>.
      </p>
      <p className="sidebar-description">Ask me about:</p>
      <p className="sidebar-description">
        📋 <strong>Admissions</strong> — UG, PG, PhD, Diploma
        <br />
        💰 <strong>Fees</strong> — tuition, semester, hostel
        <br />
        🏠 <strong>Hostel</strong> — rooms, mess, rules
        <br />
        🎓 <strong>Scholarships</strong> — merit, financial aid
        <br />
        🌍 <strong>International</strong> — exchanges, tie-ups
        <br />
        🏫 <strong>College Info</strong> — departments, campus
      </p>

      <div className="glow-divider" />

      {/* Quick Questions */}
      <p className="sidebar-section-title">💡 Try asking</p>
      {quickQuestions.map((q) => (
        <button
          key={q}
          className="quick-question-btn"
          onClick={() => onQuickQuestion(q)}
        >
          {q}
        </button>
      ))}

      <div className="glow-divider" />

      {/* New Conversation */}
      <button className="new-conversation-btn" onClick={onNewConversation}>
        🔄 New Conversation
      </button>

      {/* Footer */}
      <p className="sidebar-footer">Powered by PageIndex &amp; LangGraph</p>
    </aside>
  );
}
