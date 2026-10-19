// Preset wording for the activity strip and run checklist (contracts/api.md 1.2 `node` values).
// Presets describe the usual order of work; they never claim a finished result: the last step
// is ticked only by `run.finished` ok.

export interface PresetStep {
  label: string;
  /** Seconds this step usually takes before the next one starts. */
  seconds: number;
}

export interface Preset {
  /** Heading of the checklist card. */
  title?: string;
  /** Rotated every PHRASE_MS in the strip. */
  phrases: readonly string[];
  /** A checklist card is shown only for nodes with steps. */
  steps?: readonly PresetStep[];
}

export const PHRASE_MS = 4000;

export const GENERIC: Preset = {
  phrases: ['Working on it', 'Processing your request', 'Still working'],
};

export const PRESETS: Readonly<Record<string, Preset>> = {
  interview: {
    phrases: ['Reading your answer', 'Checking the data profile', 'Thinking of the next question', 'Writing the reply'],
  },
  plan: {
    title: 'Planning the dashboard',
    phrases: ['Reading the data profile', 'Planning the dashboard', 'Writing the build docs', 'Designing the layout', 'Rendering the prototype'],
    steps: [
      { label: 'Reading the data profile', seconds: 8 },
      { label: 'Writing build docs', seconds: 25 },
      { label: 'Creating the BigQuery view', seconds: 12 },
      { label: 'Writing the dashboard spec', seconds: 25 },
      { label: 'Checking the layout', seconds: 8 },
      { label: 'Rendering the prototype', seconds: 10 },
    ],
  },
  spec: {
    title: 'Writing the spec',
    phrases: ['Reading the build docs', 'Choosing the charts', 'Writing the dashboard spec', 'Checking the layout'],
    steps: [
      { label: 'Reading the build docs', seconds: 6 },
      { label: 'Writing the dashboard spec', seconds: 25 },
      { label: 'Checking the layout', seconds: 8 },
      { label: 'Rendering the prototype', seconds: 10 },
    ],
  },
  revise: {
    title: 'Applying your comments',
    phrases: ['Reading your comments', 'Updating the spec', 'Moving the charts', 'Rendering the prototype'],
    steps: [
      { label: 'Reading your comments', seconds: 5 },
      { label: 'Updating the dashboard spec', seconds: 20 },
      { label: 'Checking the layout', seconds: 6 },
      { label: 'Rendering the prototype', seconds: 8 },
    ],
  },
  research: {
    title: 'Researching',
    phrases: ['Searching the web', 'Reading the sources', 'Collecting the figures', 'Writing the findings'],
    steps: [
      { label: 'Searching the web', seconds: 15 },
      { label: 'Reading the sources', seconds: 30 },
      { label: 'Writing the findings', seconds: 20 },
    ],
  },
  style_extract: {
    title: 'Reading your style images',
    phrases: ['Looking at your images', 'Picking the colors', 'Reading the fonts', 'Writing the style guide'],
    steps: [
      { label: 'Reading the images', seconds: 8 },
      { label: 'Picking colors and fonts', seconds: 12 },
      { label: 'Writing the style guide', seconds: 10 },
    ],
  },
  ux_audit: {
    title: 'Auditing the prototype',
    phrases: ['Reviewing the prototype', 'Checking the contrast', 'Checking the layout', 'Writing suggestions'],
    steps: [
      { label: 'Reading the prototype', seconds: 6 },
      { label: 'Checking layout and contrast', seconds: 20 },
      { label: 'Writing suggestions', seconds: 12 },
    ],
  },
  intake: {
    title: 'Reading your data',
    phrases: ['Reading your files', 'Profiling the columns', 'Loading the data', 'Writing the data profile'],
    steps: [
      { label: 'Reading the files', seconds: 5 },
      { label: 'Profiling the columns', seconds: 12 },
      { label: 'Writing the data profile', seconds: 8 },
    ],
  },
  execute: {
    title: 'Building in Data Studio',
    phrases: ['Opening Data Studio', 'Adding the data source', 'Placing the charts', 'Styling the report', 'Checking each step'],
    steps: [
      { label: 'Opening Data Studio', seconds: 15 },
      { label: 'Connecting the data source', seconds: 30 },
      { label: 'Building the pages', seconds: 120 },
      { label: 'Checking the report', seconds: 20 },
    ],
  },
  create_build: { phrases: ['Creating the build', 'Setting up the workspace', 'Saving the build'] },
  versions: { phrases: ['Saving the version', 'Copying the spec', 'Updating the history'] },
  load_spec: { phrases: ['Loading the spec', 'Reading the version', 'Preparing the prototype'] },
  recipe: { phrases: ['Compiling the recipe', 'Ordering the steps', 'Checking the recipe'] },
  engine_login: { phrases: ['Opening the sign-in window', 'Waiting for you to sign in', 'Saving the session'] },
  consolidate: { phrases: ['Reviewing past builds', 'Collecting what worked', 'Updating the notes'] },
};

/** The preset of a node; any unknown node gets the generic phrases. */
export const presetFor = (node: string): Preset => PRESETS[node] ?? GENERIC;
