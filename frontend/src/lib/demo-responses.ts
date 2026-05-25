// Demo / pre-generated responses for the four default suggestion buttons on
// the welcome screen. When DEMO_ENABLED is true and the user submits the
// exact text of one of these suggestions, the answer is served locally
// instead of hitting the /ask endpoint.
//
// HOW TO DISABLE:
//   1. Quick toggle: set DEMO_ENABLED below to false. All submissions will
//      then go to the real /ask backend, even the four suggestion prompts.
//   2. Permanent removal: delete this file and remove the import + the
//      `if (DEMO_ENABLED && ...)` short-circuit block in src/pages/Index.tsx
//      inside handleSubmit.
//
// HOW TO ADD MORE DEMO PROMPTS:
//   Add another { prompt, content, sources? } entry below. The match is an
//   exact (case-insensitive, trimmed) string compare against the user input.

import { Source } from "@/lib/chat-store";

export const DEMO_ENABLED = true;

export interface DemoResponse {
  prompt: string;
  content: string;
  sources?: Source[];
}

export const DEMO_RESPONSES: DemoResponse[] = [
  {
    prompt: "What courses does PESU offer in Computer Science?",
    content: `## Courses in Computer Science at PESU

PES University offers a comprehensive **B.Tech in Computer Science and Engineering** program along with several specialized tracks.

### Core Programs
- **B.Tech CSE** (4 years, 160 credits)
- **B.Tech CSE (Data Science)**
- **B.Tech CSE (AI and Machine Learning)**
- **B.Tech CSE (Cybersecurity)**

### Curriculum Highlights

\`\`\`
Year 1: C Programming, Discrete Math, Digital Design
Year 2: Data Structures, Algorithms, OS, DBMS
Year 3: Computer Networks, Compiler Design, ML
Year 4: Capstone Project, Electives, Internship
\`\`\`

### Credit Distribution

$$
\\text{Total Credits} = C_{\\text{core}} + C_{\\text{elective}} + C_{\\text{project}} = 120 + 24 + 16 = 160
$$

### Elective Domains

| Domain | Courses Available |
|--------|------------------|
| AI/ML | 8 |
| Systems | 6 |
| Security | 5 |
| Theory | 4 |
| Data Science | 7 |

> The CSE department has over 80 faculty members, many with PhDs from top global institutions.`,
    sources: [
      { title: "PESU CSE Department", url: "https://pes.edu/cse", snippet: "Overview of the CSE department, faculty, and programs offered." },
      { title: "B.Tech CSE Curriculum", url: "https://pes.edu/cse/curriculum", snippet: "Detailed semester-wise curriculum for the B.Tech CSE program." },
    ],
  },
  {
    prompt: "Tell me about the placement statistics at PESU",
    content: `## Placement Statistics at PESU

PES University has consistently strong placement records across engineering programs.

### 2024 Placement Highlights

| Metric | Value |
|--------|-------|
| Students placed | 92% |
| Highest package | INR 1.2 Crores (international) |
| Average package | INR 12.5 LPA |
| Median package | INR 9.8 LPA |
| Companies visited | 350+ |

### Top Recruiters

- **Product companies**: Google, Microsoft, Amazon, Adobe, Oracle, Cisco
- **Startups**: Razorpay, CRED, Meesho, Slice, Jupiter
- **Consulting**: Deloitte, EY, McKinsey (analytics roles)
- **Core tech**: Qualcomm, Intel, Samsung R&D, Texas Instruments

### Package Distribution

$$
\\text{Average} = \\frac{\\sum_{i=1}^{n} P_i}{n} \\approx \\text{INR } 12.5 \\text{ LPA}
$$

> The Training and Placement Cell operates year-round to ensure students are industry-ready.`,
    sources: [
      { title: "PESU Placement Report 2024", url: "https://pes.edu/placements/2024", snippet: "Annual placement report with statistics and package details." },
    ],
  },
  {
    prompt: "What are the important dates for admissions?",
    content: `## Admission Process at PESU

### Eligibility Criteria

For **B.Tech programs**, candidates must meet the following requirements:

- Minimum **60%** aggregate in Class 12 (PCM)
- Valid **PESSAT** score or equivalent entrance exam

### Important Dates for 2025

| Event | Date |
|-------|------|
| PESSAT Registration Opens | January 15, 2025 |
| Last Date for Registration | April 30, 2025 |
| PESSAT Exam Window | May 1-15, 2025 |
| Results Announcement | May 25, 2025 |
| Counseling Begins | June 1, 2025 |

### Fee Structure (approximate, annual)

\`\`\`
Tuition Fee:     INR 3,20,000
Development Fee: INR   40,000
Lab Fee:         INR   25,000
----------------------------
Total:           INR 3,85,000
\`\`\`

> Scholarships are available for students scoring above 95% in their entrance examination.`,
    sources: [
      { title: "PESU Admissions 2025", url: "https://pes.edu/admissions", snippet: "Complete admission guide with eligibility criteria, process, and timeline." },
    ],
  },
  {
    prompt: "How is campus life at PES University?",
    content: `## Campus Life at PES University

PESU offers a vibrant campus experience with a strong balance of academics, culture, and recreation.

### Clubs and Organizations

The university has **60+ active student clubs** across categories:

- **Technical**: IEEE, ACM, Google DSC, Robotics Club, Open Source Community
- **Cultural**: Music Club, Dance Club, Drama Society, Photography Club
- **Sports**: Cricket, Football, Basketball, Athletics, Chess
- **Social**: NSS, Rotaract, Enactus, TEDxPESU

### Annual Events

| Event | Description | Scale |
|-------|-------------|-------|
| Aatmatrisha | Flagship cultural fest | 10,000+ attendees |
| Hackathon PESU | 48-hour coding marathon | 500+ participants |
| Pragma | Technical symposium | 3,000+ participants |

### Campus Amenities

\`\`\`
Food Courts:        3 (multi-cuisine)
WiFi Coverage:      100% campus
Hostel Capacity:    2,500 students
Medical Center:     24/7 on-campus clinic
\`\`\`

> PESU encourages holistic development through participation in clubs and committees.`,
    sources: [
      { title: "Student Life at PESU", url: "https://pes.edu/campus-life", snippet: "Overview of student activities, clubs, events, and campus culture." },
    ],
  },
];

export function findDemoResponse(query: string): DemoResponse | null {
  const q = query.trim().toLowerCase();
  return DEMO_RESPONSES.find((r) => r.prompt.toLowerCase() === q) ?? null;
}
