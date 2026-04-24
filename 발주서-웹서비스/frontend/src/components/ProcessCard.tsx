interface ProcessCardProps {
  title: string;
  description: string;
  icon: string;
  color: 'green' | 'red' | 'orange' | 'blue' | 'amber';
  onClick: () => void;
}

const colorMap = {
  green: {
    border: 'border-l-green-500',
    bg: 'bg-green-50',
    iconBg: 'bg-green-100',
    text: 'text-green-700',
  },
  red: {
    border: 'border-l-red-500',
    bg: 'bg-red-50',
    iconBg: 'bg-red-100',
    text: 'text-red-700',
  },
  orange: {
    border: 'border-l-orange-500',
    bg: 'bg-orange-50',
    iconBg: 'bg-orange-100',
    text: 'text-orange-700',
  },
  blue: {
    border: 'border-l-blue-500',
    bg: 'bg-blue-50',
    iconBg: 'bg-blue-100',
    text: 'text-blue-700',
  },
  amber: {
    border: 'border-l-amber-500',
    bg: 'bg-amber-50',
    iconBg: 'bg-amber-100',
    text: 'text-amber-700',
  },
};

function ProcessCard({ title, description, icon, color, onClick }: ProcessCardProps) {
  const colors = colorMap[color];

  return (
    <button
      onClick={onClick}
      className={`w-full text-left bg-white rounded-xl shadow-sm border border-gray-200
                  border-l-4 ${colors.border}
                  hover:shadow-md hover:-translate-y-0.5
                  active:translate-y-0 active:shadow-sm
                  transition-all duration-200 ease-out
                  p-5 group`}
    >
      <div className="flex items-start gap-4">
        <div
          className={`w-12 h-12 ${colors.iconBg} rounded-xl flex items-center justify-center
                      text-2xl flex-shrink-0 group-hover:scale-110 transition-transform duration-200`}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-bold text-gray-900 mb-1">{title}</h3>
          <p className="text-sm text-gray-500 leading-relaxed">{description}</p>
        </div>
        <svg
          className="w-5 h-5 text-gray-300 group-hover:text-gray-500 flex-shrink-0 mt-1
                     group-hover:translate-x-0.5 transition-all duration-200"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </button>
  );
}

export default ProcessCard;
