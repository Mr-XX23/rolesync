import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Database, GraduationCap, Compass, HelpCircle } from 'lucide-react';
import { useAppDispatch } from '../store';
import { setActiveRole } from '../store/roleSlice';
import type { RolePack } from '../store/roleSlice';

interface PersonaCard {
  id: RolePack;
  title: string;
  subtitle: string;
  description: string;
  icon: React.ComponentType<any>;
  themeClass: string;
  badge: string;
}

export const RolePicker: React.FC = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();

  const personas: PersonaCard[] = [
    {
      id: 'sales',
      title: 'Salesman Engine',
      subtitle: 'pgvector & Knowledge Vault',
      description: 'Ingest business sheets, tune chunk overlaps, and calibrate retrieval augmented generation parameters for enterprise sales.',
      icon: Database,
      themeClass: 'from-amber-500/10 to-orange-500/5 border-amber-500/30 hover:border-amber-500 text-amber-700 dark:text-amber-300 dark:from-amber-500/5 dark:to-orange-500/2',
      badge: 'ENTERPRISE',
    },
    {
      id: 'teacher',
      title: 'AI Tutor Console',
      subtitle: 'Curriculum & Pedagogy',
      description: 'Generate adaptive lesson scripts, structure course pathways, and deploy student mentoring models.',
      icon: GraduationCap,
      themeClass: 'from-emerald-500/10 to-teal-500/5 border-emerald-500/30 hover:border-emerald-500 text-emerald-700 dark:text-emerald-300 dark:from-emerald-500/5 dark:to-teal-500/2',
      badge: 'EDUCATOR',
    },
    {
      id: 'student',
      title: 'Student Desk',
      subtitle: 'Interactive Learning Hub',
      description: 'Interact with trained companion agents, access knowledge databases, and solve targeted study assignments.',
      icon: Compass,
      themeClass: 'from-blue-500/10 to-indigo-500/5 border-blue-500/30 hover:border-blue-500 text-blue-700 dark:text-blue-300 dark:from-blue-500/5 dark:to-indigo-500/2',
      badge: 'LEARNER',
    },
  ];

  const handleSelectRole = (role: RolePack) => {
    dispatch(setActiveRole(role));
    if (role === 'sales') {
      navigate('/salesman/knowledge-vault');
    } else {
      alert(`The ${role} profile workspace is configured but inactive. Redirecting to mock console...`);
    }
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-center items-center py-12 px-4 sm:px-6 relative overflow-hidden">
      {/* Dynamic Background Blurs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl -z-10 animate-pulse duration-5000"></div>
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-secondary/15 rounded-full blur-3xl -z-10 animate-pulse duration-7000"></div>

      <div className="w-full max-w-4xl text-center space-y-8 relative z-10">
        {/* Branding Header */}
        <div className="space-y-3 animate-in fade-in slide-in-from-top-4 duration-500">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-primary/10 text-primary border border-primary/20 rounded-full text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Select Workspace Persona</span>
          </div>
          <h1 className="text-4xl md:text-5xl font-serif font-bold text-foreground leading-tight">
            Configure Your Environment
          </h1>
          <p className="text-muted-foreground max-w-lg mx-auto text-sm md:text-base">
            Choose an operating role to synchronize models, calibrate parameters, and access specialized agent matrices.
          </p>
        </div>

        {/* Persona Launchpad Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-6">
          {personas.map((persona, index) => {
            const Icon = persona.icon;
            return (
              <div
                key={persona.id}
                onClick={() => handleSelectRole(persona.id)}
                className={`group relative bg-card border rounded-2xl p-6 text-left cursor-pointer transition-all duration-300 hover:-translate-y-1.5 hover:shadow-lg active:scale-97 flex flex-col ${persona.themeClass} animate-in fade-in slide-in-from-bottom-4 duration-500`}
                style={{ animationDelay: `${index * 100}ms` }}
              >
                {/* Badge */}
                <div className="absolute top-4 right-4 bg-background/80 dark:bg-card/80 border border-border/80 rounded-full px-2.5 py-0.5 text-[9px] font-mono font-bold tracking-widest">
                  {persona.badge}
                </div>

                {/* Icon Shell */}
                <div className="w-12 h-12 rounded-2xl bg-background/90 dark:bg-card/90 border border-border flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300 shadow-2xs">
                  <Icon className="w-6 h-6" />
                </div>

                {/* Typography */}
                <h3 className="font-serif text-lg font-bold text-foreground mb-1 group-hover:text-primary transition-colors">
                  {persona.title}
                </h3>
                <p className="text-xs font-semibold text-muted-foreground/90 font-mono tracking-wide mb-3">
                  {persona.subtitle}
                </p>
                <p className="text-xs leading-relaxed text-muted-foreground/80 flex-1">
                  {persona.description}
                </p>

                {/* Footer Interaction Arrow */}
                <div className="mt-6 pt-4 border-t border-border/40 flex items-center justify-between text-xs font-bold group-hover:translate-x-1 transition-transform duration-200">
                  <span className="text-muted-foreground group-hover:text-primary transition-colors">
                    Launch Environment
                  </span>
                  <span>→</span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Support Help Footnote */}
        <div className="pt-8 text-center text-xs text-muted-foreground flex items-center justify-center gap-1.5 animate-in fade-in duration-700">
          <HelpCircle className="w-4 h-4 text-muted-foreground/60" />
          <span>Need custom permissions? Contact your enterprise operator.</span>
        </div>
      </div>
    </div>
  );
};
