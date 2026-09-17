/** @type {import('stylelint').Config} */
export default {
  extends: "stylelint-config-standard",
  // Taro emits custom host selectors (View/Text/taro-input-core) and the
  // prototype intentionally keeps compact one-line SCSS.  Keep syntax and
  // unknown-property checks from the standard preset while disabling rules
  // that would rewrite valid cross-platform selectors or token notation.
  rules: {
    "declaration-block-single-line-max-declarations": null,
    "color-hex-length": null,
    "color-function-alias-notation": null,
    "color-function-notation": null,
    "alpha-value-notation": null,
    "font-family-name-quotes": null,
    "no-descending-specificity": null,
    "selector-type-case": null,
    "selector-type-no-unknown": null,
    "at-rule-empty-line-before": null,
    "comment-empty-line-before": null,
    "media-feature-range-notation": null,
    "shorthand-property-no-redundant-values": null,
  },
};
