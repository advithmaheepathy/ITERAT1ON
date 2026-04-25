import React from 'react';

const COLORS = {
  0: '#1f2937', // dark gray (Unburned)
  1: '#facc15', // yellow (Low)
  2: '#f97316', // orange (Moderate)
  3: '#dc2626', // red (Severe)
};

const LABELS = {
  0: 'Unburned',
  1: 'Low Severity',
  2: 'Moderate Severity',
  3: 'Severe Burn'
};

export default function BurnMap({ map }) {
  if (!map || map.length === 0) return (
    <div className="flex items-center justify-center h-48 bg-slate-800/50 rounded-xl border border-slate-700/50">
      <p className="text-slate-500 text-sm">Awaiting burn severity data...</p>
    </div>
  );

  const rows = map.length;
  const cols = map[0].length;
  const flatMap = map.flat();

  return (
    <div className="relative overflow-hidden rounded-xl bg-slate-950 border border-slate-800/60 flex flex-col items-center justify-center p-6 shadow-2xl">
      {/* Generic satellite background image */}
      <div 
        className="absolute inset-0 bg-cover bg-center opacity-20 pointer-events-none"
        style={{ backgroundImage: 'url("https://images.unsplash.com/photo-1614729939124-032f0b56c9ce?q=80&w=1200&auto=format&fit=crop")' }}
      />
      
      {/* Map Header */}
      <div className="w-full flex justify-between items-center mb-6 relative z-10">
        <h3 className="text-sm font-bold text-white tracking-wide uppercase flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          Burn Severity Map
        </h3>
        <span className="text-[10px] font-mono text-slate-400 bg-slate-900 px-2 py-1 rounded border border-slate-700">
          {cols}x{rows} PX
        </span>
      </div>

      {/* Burn Map Grid */}
      <div 
        className="relative z-10 rounded shadow-[0_0_30px_rgba(220,38,38,0.15)] transition-all duration-500 hover:scale-105"
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${cols}, 4px)`,
          gridTemplateRows: `repeat(${rows}, 4px)`,
          gap: 0,
          opacity: 0.8
        }}
      >
        {flatMap.map((val, idx) => (
          <div 
            key={idx}
            className="transition-colors duration-300"
            style={{
              width: '4px',
              height: '4px',
              backgroundColor: COLORS[val] || COLORS[0],
            }}
            title={LABELS[val] || 'Unknown'}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="mt-8 flex flex-wrap items-center justify-center gap-4 relative z-10">
        {Object.entries(COLORS).map(([key, color]) => (
          <div key={key} className="flex items-center gap-2">
            <div 
              className="w-3 h-3 rounded-sm shadow-sm"
              style={{ backgroundColor: color }}
            />
            <span className="text-xs text-slate-400 font-medium">{LABELS[key]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
