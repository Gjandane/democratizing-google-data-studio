// Preset wording for the activity strip and run checklist (contracts/api.md 2.0 `node` values).
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
  context: {
    title: 'Drafting the context',
    phrases: ['Reading the data profile', 'Reading your notes', 'Defining the KPIs', 'Checking the fields'],
    steps: [
      { label: 'Reading the data profile', seconds: 6 },
      { label: 'Drafting KPIs and derived fields', seconds: 20 },
      { label: 'Checking every field', seconds: 4 },
    ],
  },
  outline_propose: {
    title: 'Proposing questions',
    phrases: ['Reading the context', 'Grouping the sections', 'Proposing questions', 'Checking the KPIs'],
    steps: [
      { label: 'Reading the context', seconds: 4 },
      { label: 'Proposing sections and questions', seconds: 18 },
      { label: 'Checking the KPI references', seconds: 3 },
    ],
  },
  outline_other: { phrases: ['Reading your question', 'Normalizing the question', 'Adding it to the outline'] },
  outline_suggest: { phrases: ['Reading the section', 'Suggesting questions', 'Adding them unselected'] },
  blueprint: {
    title: 'Drafting the blueprint',
    phrases: ['Choosing the charts', 'Mapping the fields', 'Checking feasibility', 'Dry-running the view'],
    steps: [
      { label: 'Choosing a chart per question', seconds: 20 },
      { label: 'Checking feasibility', seconds: 8 },
      { label: 'Dry-running the BigQuery view', seconds: 10 },
    ],
  },
  prototype: {
    title: 'Rendering the prototype',
    phrases: ['Laying out the pages', 'Writing the dashboard spec', 'Checking the layout', 'Rendering the prototype'],
    steps: [
      { label: 'Laying out the pages', seconds: 10 },
      { label: 'Checking the layout', seconds: 6 },
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
  reference_extract: {
    title: 'Reading your references',
    phrases: ['Inspecting your images', 'Reading the layout', 'Checking the style', 'Saving the reference summary'],
  },
  reference_delete: { phrases: ['Removing the reference', 'Updating your references'] },
  capability_check: { phrases: ['Checking your requirements', 'Checking what this app supports', 'Preparing alternatives'] },
  synthetic_schema: { phrases: ['Reading the reference fields', 'Proposing sample columns', 'Preparing the sample schema'] },
  synthetic_generate: { phrases: ['Generating invented sample rows', 'Preparing the sample CSV', 'Loading sample data'] },
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
