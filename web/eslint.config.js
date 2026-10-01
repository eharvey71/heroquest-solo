// One rule, on purpose. TypeScript lets a closure read a `const` that
// is declared further down the same scope, because the closure MIGHT
// run later -- but a callback handed to Array.map during render runs
// at once, and the shipped bundle threw "Cannot access before
// initialization" on every game load (GameView's Journal derivation
// read `playable`, declared 70 lines below). `tsc` can't see it; this
// can. Runs in firebase.json's hosting predeploy hook, before the
// build, so it aborts the deploy. Functions are exempt (hoisted).
import tseslint from "typescript-eslint";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  {
    files: ["src/**/*.ts", "src/**/*.tsx"],
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { "@typescript-eslint": tseslint.plugin },
    rules: {
      "@typescript-eslint/no-use-before-define": [
        "error",
        { functions: false, classes: true, variables: true, enums: true, typedefs: false },
      ],
    },
  },
];
