export default class UnfilledRequiredParameters extends Error {
  constructor(parameters: string[]) {
    super(`Required parameters are missing: ${parameters.join(", ")}`);
    this.name = "UnfilledRequiredParameters";
  }
}
