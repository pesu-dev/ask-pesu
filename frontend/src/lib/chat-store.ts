export interface Source {
  title: string;
  url: string;
  snippet: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  timestamp: Date;
  /** True when content arrived via live /ask streaming (skip the fake word animation in ChatMessage). */
  streamed?: boolean;
  /** Optional ephemeral status text (e.g. "Searching documents...") shown while tokens are still arriving. */
  status?: string;
  /** Set when the stream aborted mid-flight (backend error, network drop, /ask returned non-2xx). */
  error?: string;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

const PREGENERATED_RESPONSES: { content: string; sources: Source[] }[] = [
  {
    content: `## Courses in Computer Science at PESU

PES University offers a comprehensive **B.Tech in Computer Science and Engineering** program along with several specialized tracks:

### Core Programs
- **B.Tech CSE** (4 years, 160 credits)
- **B.Tech CSE (Data Science)**
- **B.Tech CSE (AI and Machine Learning)**
- **B.Tech CSE (Cybersecurity)**

### Curriculum Highlights

The CSE curriculum covers foundational and advanced topics:

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

Students can specialize through electives in:

| Domain | Courses Available |
|--------|------------------|
| AI/ML | 8 |
| Systems | 6 |
| Security | 5 |
| Theory | 4 |
| Data Science | 7 |

> The CSE department has over 80 faculty members, many with PhDs from top global institutions.`,
    sources: [
      { title: "PESU CSE Department", url: "https://pes.edu/cse", snippet: "Overview of the Computer Science and Engineering department, faculty, and programs offered." },
      { title: "B.Tech CSE Curriculum", url: "https://pes.edu/cse/curriculum", snippet: "Detailed semester-wise curriculum for the B.Tech CSE program." },
      { title: "Specialization Tracks", url: "https://pes.edu/cse/tracks", snippet: "Information about specialized tracks in AI/ML, Data Science, and Cybersecurity." },
    ],
  },
  {
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

Major companies that recruit from PESU include:

- **Product companies**: Google, Microsoft, Amazon, Adobe, Oracle, Cisco
- **Startups**: Razorpay, CRED, Meesho, Slice, Jupiter
- **Consulting**: Deloitte, EY, McKinsey (analytics roles)
- **Core tech**: Qualcomm, Intel, Samsung R&D, Texas Instruments

### Package Distribution

$$
\\text{Average} = \\frac{\\sum_{i=1}^{n} P_i}{n} = \\frac{\\text{INR } 875 \\text{ Cr}}{700} \\approx \\text{INR } 12.5 \\text{ LPA}
$$

### Preparation Resources

The university provides:

1. **Pre-placement training** from 5th semester
2. **Mock interviews** with industry professionals
3. **Coding contests** hosted weekly on internal OJ
4. **Resume workshops** and LinkedIn optimization sessions

> The Training and Placement Cell operates year-round to ensure students are industry-ready.`,
    sources: [
      { title: "PESU Placement Report 2024", url: "https://pes.edu/placements/2024", snippet: "Annual placement report with statistics, top recruiters, and package details." },
      { title: "Training and Placement Cell", url: "https://pes.edu/tpc", snippet: "Information about the placement cell, training programs, and recruitment process." },
    ],
  },
  {
    content: `## Admission Process at PESU

### Eligibility Criteria

For **B.Tech programs**, candidates must meet the following requirements:

- Minimum **60%** aggregate in Class 12 (PCM)
- Valid **PESSAT** score or equivalent entrance exam
- Age limit: Born on or after July 1, 2006

### Selection Formula

The merit score is computed as:

$$
M = 0.5 \\times S_{\\text{PESSAT}} + 0.3 \\times P_{12} + 0.2 \\times P_{\\text{extra}}
$$

Where:
- $S_{\\text{PESSAT}}$ = Normalized PESSAT score (out of 100)
- $P_{12}$ = Class 12 percentage normalized
- $P_{\\text{extra}}$ = Extra-curricular achievement score

### Important Dates for 2025

| Event | Date |
|-------|------|
| PESSAT Registration Opens | January 15, 2025 |
| Last Date for Registration | April 30, 2025 |
| PESSAT Exam Window | May 1-15, 2025 |
| Results Announcement | May 25, 2025 |
| Counseling Begins | June 1, 2025 |

### Fee Structure

The approximate annual fee for B.Tech programs:

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
      { title: "PESSAT Exam Details", url: "https://pes.edu/pessat", snippet: "Information about PESSAT examination pattern, syllabus, and preparation resources." },
      { title: "Fee Structure 2024-25", url: "https://pes.edu/fees", snippet: "Detailed fee structure for all programs offered at PES University." },
    ],
  },
  {
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
| Convocation | Graduation ceremony | University-wide |

### Campus Amenities

\`\`\`
Food Courts:        3 (multi-cuisine)
Cafeterias:         5
WiFi Coverage:      100% campus
Hostel Capacity:    2,500 students
Medical Center:     24/7 on-campus clinic
Transport:          University bus service (40+ routes)
\`\`\`

### Hostel Life

The hostels provide:

1. **Single and double occupancy** rooms
2. **24/7 security** with biometric access
3. **Common rooms** with TV, indoor games
4. **Laundry service** and housekeeping
5. **Study rooms** open until midnight

### Location Advantage

The RR Campus is located on Hosur Road, Bangalore, providing easy access to:

- **Koramangala** tech hub (15 min)
- **Electronic City** (10 min)
- **MG Road / City Center** (30 min)

> PESU encourages holistic development through mandatory participation in at least one club or committee.`,
    sources: [
      { title: "Student Life at PESU", url: "https://pes.edu/campus-life", snippet: "Overview of student activities, clubs, events, and campus culture." },
      { title: "Hostel Information", url: "https://pes.edu/hostels", snippet: "Details about hostel facilities, fees, and accommodation options." },
      { title: "Clubs and Committees", url: "https://pes.edu/clubs", snippet: "Complete list of student-run clubs and organizations at PES University." },
    ],
  },
];

let responseIndex = 0;

export function getNextResponse(): { content: string; sources: Source[] } {
  const response = PREGENERATED_RESPONSES[responseIndex % PREGENERATED_RESPONSES.length];
  responseIndex++;
  return response;
}

export function createId(): string {
  return Math.random().toString(36).substring(2, 15);
}

export function createConversation(title: string = "New Chat"): Conversation {
  return {
    id: createId(),
    title,
    messages: [],
    createdAt: new Date(),
    updatedAt: new Date(),
  };
}
