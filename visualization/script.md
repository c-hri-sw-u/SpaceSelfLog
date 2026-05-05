# Presentation Script

## cover

### 01

Good morning, everyone. My name is Chris Wu, and today I'm presenting: Physical-World Observation for Personal AI Agent Personalization. Such a long name.

[Pause]

First, I want to ask you a question: how well do you actually know your own life?

Not your calendar. I mean, the actual texture of it.

Think you know it well? Here's a number: across most chronic diseases, genetic factors account for less than 20% of the risk. The rest is lifestyle. Most of the time, we're simply not paying attention to ourselves.

And if you asked someone who lives with you to describe your daily life — their version would probably differ from yours. They might be closer to the truth.

The same thing happens when we design our own homes, or describe what we want to a designer. We very often end up discovering a significant mismatch. The spaces we thought we'd love go untouched. The corners we actually use are barely big enough.

[Pause]

So I've been imagining a future — where an agent that observes how you actually live becomes as ordinary as a smartwatch tracking your steps.

Today I'm here to answer two questions: how far away is that future — and how do we make sure it's a future we actually want.

## Intro

### 02 — The Claw

Before we get into the research — a few terms worth being precise about.

### 03 — Personal AI Agents are Here

You've probably used something like ChatGPT. You ask a question, it answers, you close it. Tomorrow you open it again — it doesn't know you were ever there. That's the AI assistant model.

A personal AI agent works on a different premise. It has persistent memory. It runs tasks on your behalf. It carries your context forward — your work, your patterns, your preferences — across every session. You don't reintroduce yourself every time.

That shift — from something that answers to something that knows you — is what makes personalization possible. And it's why the gap we're going to talk about actually matters.

### 04 — The OpenClaw Fever

One platform is driving a lot of this: OpenClaw. And the scale of adoption caught most people off guard.

### 05 — What is OpenClaw

You can view OpenClaw as the operating system for your agent. While models like Claude or GPT provide the reasoning, OpenClaw handles what surrounds it — your memory, your tasks, your local environment. It's what lets an agent remember you, session after session.

### 06 — OpenClaw's Spreading

The deployment map gives you a sense of scale. This happened within months.

### 07 — OpenClaw's GitHub Stars Growth

And it becomes the fastest growing open source project in the history

### 08 — Personalization

I opened with a question: how well do you actually know your own life? Personalization asks the same thing of a system — how well does it know you?

Blom defined it in 2000 as changing a system to increase its personal relevance to the individual. My framing is simpler: the service fits — or better yet, exceeds — your expectations.

Think of it as a spectrum. At one end, systems that don't notice you exist. At the other, human conversation — where every word, every pause, is continuous adjustment.

### 09 — Why Personalization Matters

For an AI agent, where you sit on that spectrum determines everything.

On the left, a generic agent sees every task the same way regardless of who's asking. Your context, your goals, your preferences all get flattened.

On the right, a personalized agent fuses your history, your preferences, your workflows. The same task comes in — and it reaches the right outcome.

## The Blind Spot

### 10 — The Blind Spot

But there's a blind spot.

All of that memory for AI agents today — is built entirely from your digital life.

The rest of your life is invisible to it.

### 11 — Two Worlds

We live in two worlds simultaneously.

On the left is the digital dimension — browser tabs, calendar, chat logs. AI agents are already good at it.

On the right is the physical world. The agent knows your calendar, but not that your desk is cluttered, your focus has drifted, and the coffee is your third of the morning.

Right now, our agents are personalizing from only half the picture.

### 12 — Research Landscape

This idea — recording your life and retrieving it later — isn't new.

Vannevar Bush imagined the Memex in 1945: a machine that could store and link everything you read. Gordon Bell spent a decade photographing his every waking moment with MyLifeBits.

What's changed is that models can now extract structured meaning from images. The question becomes: does continuous observation actually help an agent understand you better? That's what this research tries to answer.

### 13 — Research Questions

Three questions: what can physical observation reveal that digital traces can't, when does it actually help, and what does it take to build.

## Design Rationale

### 14 — Design Rationale

Before the system itself — a few key decisions that shaped everything.

### 15 — Why Egocentric Vision?

The most fundamental choice was to use egocentric vision — a first-person wearable camera.

Your field of view is already a map of your attention. Whatever you're looking at is, by definition, what you're engaging with. No external sensor can tell you that.

And unlike a fixed camera, a wearable goes everywhere you do — every room, every transition. A single frame captures your surroundings, your activity, and the objects around you at once.

### 16 — Why OpenClaw?

The second decision was to build on OpenClaw rather than a custom agent.

OpenClaw personalizes through plain text files — markdown documents describing who you are, what you're working on, what you prefer. Every session, the agent reads those files before it does anything else.

That means we can inject physical-world observations directly into the agent's memory without touching its core architecture. We're speaking the system's own language.

### 17 — How OpenClaw works

At the start of every session, OpenClaw assembles a context window from markdown files — your persona, your preferences, your recent logs. The model reads all of this before the conversation begins.

The memory is plain text. You can open it, read it, edit it. It's not a black box.

## System Design

### 18 — System Design

Now let's look at how this actually works — how raw video from a wearable becomes the kind of knowledge that makes an agent feel personal.

### 19 — Abstract Pipeline

The big picture: a continuous loop — Collection, Compression, Integration, Feedback.

I want to pause on Compression, because it's the strategic heart of this project.

The physical world generates an overwhelming amount of data. The question isn't 'how do we capture everything?' It's: 'how do we decide what matters?'

In this pipeline, to compress is to understand. The system doesn't try to remember every frame — it filters to identify key events, moments that actually change something about who you are. By combining AI reasoning with your own feedback, thousands of raw images become a handful of meaningful insights.

### 20 — The Pipeline & Data Flow

This is the five-layer pipeline.

Notice the boundary in the middle. Capture and Preprocessing run on your phone — locally, on your body. The data then moves to your computer, where Inference and Memory do the heavy lifting. Retrieval connects everything back to the agent.

One side gathers; the other decides what matters. That division of labor is what keeps the system light enough to run all day.

### 21 — Layer 1 Capture & Layer 1.5 Preprocess

The first challenge: how do you capture a human life without recording everything?

The answer is adaptive capture. Instead of filming at a fixed interval, the system listens — monitoring ambient sound, movement, and scene changes. When those signals appear, the camera activates.

If you're working quietly at your desk for thirty minutes, almost nothing is recorded. The moment you move to another room or start a conversation, it wakes up.

Mostly quiet, selectively attentive.

### 22 — Capture Monitor

To tune all of this, I built a monitor page streaming the camera from my phone — so I could watch the system's behavior and adjust the parameters in real time.

### 23 — Layer 2 Inference

Once we have those snapshots, the Inference layer looks for meaning.

If you're sitting at a kitchen table with a laptop and a half-eaten sandwich, it doesn't list the objects. It reads the context: this person is probably having a working lunch.

The output is a structured observation — a readable note the agent can use directly.

### 24 — Layer 3 Memory

How do we organize this knowledge? The memory has four layers — from raw daily logs at the bottom up to long-term behavioral patterns at the top. Think of it as working memory on one end, long-term memory on the other as human.

What matters most: it can be corrected. If the system misreads a scene, you can open the file, edit it, and teach it what actually happened. It's a memory you can audit.

### 25 — Server Monitor

I also built a dashboard. In the center, the batch feed — raw snapshots coming in, immediately translated into structured observations. On the right, the memory state showing the agent's running journal, tracking current state and daily highlights as they accumulate.

### 26 — Layer 3.5 Retrieval

Finally, the Retrieval layer — where stored knowledge becomes active assistance.

It works three ways. Bootstrap: every session begins with the agent already up to speed on your recent context.

On-Demand: if you ask 'where did I leave that book I was reading?' the agent searches its physical logs and answers from observation, not assumption.

Proactive: the agent can notice something has changed in your physical environment and initiate a conversation on its own.

### 27 — Full Pipeline Overview

Taken together: a continuous, structured record of a person's physical life, connected to the agent that works for them.

## Study Design

### 28 — Study Design

To find out if this is a future we actually want, I had to live in it. A two-week autoethnographic study — research through design. I was both the designer and the subject.

### 29 — Study Design

The study ran in two phases. First, calibration — I tuned the system until it was behaving reliably. Then I froze everything and simply lived with it.

### 30 — Data Collection

That produced three streams of data: egocentric images, transcripts of every conversation with the agent, and a daily journal where I wrote down what the system got right and what it got wrong.

### 31 — Experimental Protocol

The observation itself worked in three modes. Passive — I went about my day and let the system run. Structured probes — at specific moments, I asked the agent to recall something from earlier. And proactive triggers — a scheduled task that let the agent start a conversation on its own.

### 32 — Study Device

All of this ran through one device — an off-the-shelf iPhone. Camera, microphone, motion sensors, all built in.

The mounting decision mattered more than I expected. I went with chest-mounted over head-mounted — less attentional precision, but comfortable enough to forget it was there. If you're aware of the device, you're not behaving naturally.

Yes, I walked around like this for two weeks.

### 33 — Design Iteration Log

Every change during calibration was logged here. What was adjusted, why, and what effect it had.

In a study where I'm both designer and subject, this log is the audit trail that keeps the process honest.

### 34 — Autoethnographic Journal

And this is the journal — written observations alongside the agent's conversation transcripts.

Where it got things right. Where it missed. What surprised me.

## Results

### 35 — Results

What did two weeks actually produce?

### 36 — Full Timeline Wall

This is part of my life in that 2 weeks, as seen by the agent. Each image is a moment the system judged worth capturing.

### 37 — Activity Daily Rhythm Matrix

Looking more closely at the data — this matrix maps what I was doing against time of day, across the full two weeks.

### 38 — Object Co-occurrence Network

This network maps object co-occurrence — what appeared together in the same scene.

And I generated an image to show AI's perspective.

### 39 — Context to Activity Flow

And beyond objects — location itself turned out to be one of the strongest signals.

Where I was — desk, kitchen, couch — strongly predicted what I was doing next. If the agent knows where I am, it already has a strong guess about what I need.

### 40 — Apartment Activity Heatmap

And we can map the data onto the floor plan of my apartment.

We can see where life actually concentrates. This is the mismatch I mentioned at the start.

The agent now knows this.

### 41 — Integrated Spatial Activity Map

This final map adds one more layer — not just where, but what I was doing there, and how often.

What this would mean for someone who designs spaces: an architect doesn't need just square meters — they need to know how a space is actually inhabited. Right now, the only way to get that is to ask, and trust that the person remembers.

Imagine instead: they talk to the agent. 

When some day agents become reliable enough, that conversation is closer than it sounds.

### 42 — What the Agent Learned About Me

At the start I asked: how well do you actually know your own life? After two weeks, the agent's answer is that it knows some things about me that I hadn't put into words myself.

It noticed my drink choices track what kind of work I'm doing. My late-night kitchen trips aren't random — they're a consistent decompression loop. I always work with both paper and a screen.

## Discussion

### 43 — Answering the Research Questions

So — what did the system actually deliver against each question?

For RQ1: yes, it captures something digital logs can't — the in-between moments, the drift between tasks. But raw observation doesn't automatically become insight. That requires a dedicated reasoning step.

For RQ2 and RQ3 — let me show you two specific moments.

### 44

Two moments — one that worked, one that didn't.

The connection: I came back from rock climbing without logging anything. The agent noticed the gap in my day and asked if I'd gone climbing. It was right. I had asked it climbing questions before, but I didn't expect it to connect that to my actual life — to notice I was gone and guess correctly where. It felt, for a moment, like talking to someone who actually knew me.

The disconnection: I was crouching down, reorganizing my fridge. The agent reached out to let me know I was cleaning my refrigerator coils.

## Conclusion

### 45 — System Limitations

So what are the boundaries of this future?

The Hawthorne effect was real — but I forgot about the camera surprisingly quickly when I was deeply focused. The social friction with other people, on the other hand, was immediate and impossible to ignore.

And the VLM over-interpretation issue isn't just a bug. These models are built to find meaning. Give them a passive environment, and they'll invent it.

### 46 — The Life It Witnessed

The agent had my data, and its insights about my life. I asked it to draw a manga to depict my life. This is what it made.

This is a new possibility for understanding how we actually live.

## End

### 47 — Thank You

And with that, I'll conclude my presentation. Thank you very much for your time and attention.
