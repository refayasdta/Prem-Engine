const acceptanceUrl = process.env.ACCEPTANCE_URL;

if (!acceptanceUrl) {
  throw new Error("ACCEPTANCE_URL is required");
}

module.exports = {
  ci: {
    collect: {
      url: [acceptanceUrl],
      numberOfRuns: 3,
      settings: {
        preset: "desktop",
      },
    },
    assert: {
      assertions: {
        "categories:accessibility": ["error", { minScore: 0.95 }],
        "categories:best-practices": ["error", { minScore: 0.9 }],
        "categories:performance": ["error", { minScore: 0.75 }],
        "categories:seo": ["error", { minScore: 0.9 }],
      },
    },
    upload: {
      target: "filesystem",
      outputDir: ".lighthouseci",
    },
  },
};
