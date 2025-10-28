interface TulipIllustrationProps {
  size?: "small" | "large"
}

export function TulipIllustration({ size = "large" }: TulipIllustrationProps) {
  const sizeClasses = size === "large" ? "w-32 h-40 sm:w-40 sm:h-52 md:w-44 md:h-56" : "w-16 h-20 sm:w-20 sm:h-24"

  return (
    <svg
      viewBox="0 0 180 240"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`drop-shadow-sm ${sizeClasses}`}
    >
      {/* Main tulip flower - elegant, refined petals */}
      {/* Left petal - delicate curves */}
      <path
        d="M 70 85 Q 52 58, 58 28 Q 62 15, 68 18 Q 75 32, 80 55 Q 83 70, 82 85 Z"
        stroke="#3A3A3A"
        strokeWidth="0.7"
        fill="rgba(255, 255, 255, 0.85)"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      />

      {/* Center petal - tall and graceful */}
      <path
        d="M 82 85 Q 85 45, 88 20 Q 89 8, 92 12 Q 95 35, 93 65 Q 92 78, 93 85 Z"
        stroke="#3A3A3A"
        strokeWidth="0.7"
        fill="rgba(255, 255, 255, 0.9)"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      />

      {/* Right petal - elegant sweep */}
      <path
        d="M 93 85 Q 90 55, 92 35 Q 96 20, 102 25 Q 110 42, 115 60 Q 118 75, 108 85 Z"
        stroke="#3A3A3A"
        strokeWidth="0.7"
        fill="rgba(255, 255, 255, 0.85)"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.95"
      />

      {/* Inner petal details - very fine fountain pen lines */}
      <path
        d="M 72 75 Q 74 52, 76 32"
        stroke="#3A3A3A"
        strokeWidth="0.4"
        fill="none"
        opacity="0.25"
        strokeLinecap="round"
      />
      <path
        d="M 88 78 Q 89 53, 90 28"
        stroke="#3A3A3A"
        strokeWidth="0.4"
        fill="none"
        opacity="0.25"
        strokeLinecap="round"
      />
      <path
        d="M 104 75 Q 102 52, 100 32"
        stroke="#3A3A3A"
        strokeWidth="0.4"
        fill="none"
        opacity="0.25"
        strokeLinecap="round"
      />

      {/* Additional delicate petal veins */}
      <path
        d="M 68 70 Q 70 55, 72 40"
        stroke="#3A3A3A"
        strokeWidth="0.3"
        fill="none"
        opacity="0.2"
        strokeLinecap="round"
      />
      <path
        d="M 108 70 Q 106 55, 104 40"
        stroke="#3A3A3A"
        strokeWidth="0.3"
        fill="none"
        opacity="0.2"
        strokeLinecap="round"
      />

      {/* Stem - refined and elegant */}
      <path
        d="M 90 85 Q 88 125, 86 165 Q 85 185, 86 220"
        stroke="#3A3A3A"
        strokeWidth="1.2"
        fill="none"
        strokeLinecap="round"
        opacity="0.9"
      />

      {/* Left leaf - graceful and delicate */}
      <path
        d="M 86 145 Q 65 148, 50 156 Q 45 159, 47 162 Q 54 164, 72 160 Q 83 156, 86 152"
        stroke="#3A3A3A"
        strokeWidth="0.7"
        fill="rgba(255, 255, 255, 0.7)"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />

      {/* Leaf vein - very fine */}
      <path
        d="M 86 148 Q 72 152, 58 158"
        stroke="#3A3A3A"
        strokeWidth="0.4"
        fill="none"
        opacity="0.3"
        strokeLinecap="round"
      />

      {/* Right leaf - elegant sweep */}
      <path
        d="M 86 185 Q 107 188, 122 196 Q 127 199, 125 202 Q 118 204, 100 200 Q 89 196, 86 192"
        stroke="#3A3A3A"
        strokeWidth="0.7"
        fill="rgba(255, 255, 255, 0.7)"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.9"
      />

      {/* Leaf vein - very fine */}
      <path
        d="M 86 188 Q 100 192, 114 198"
        stroke="#3A3A3A"
        strokeWidth="0.4"
        fill="none"
        opacity="0.3"
        strokeLinecap="round"
      />
    </svg>
  )
}
