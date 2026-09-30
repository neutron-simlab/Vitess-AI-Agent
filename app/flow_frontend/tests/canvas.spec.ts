import { test, expect } from "@playwright/test";

test("canvas lives in chat, supports real dragging and hands off a locked plan", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("radiogroup", { name: "Starter topics" })
    .getByText("Build pipeline", { exact: true })
    .click();
  const canvas = page.getByRole("region", { name: "Pipeline builder" });
  await expect(canvas).toBeVisible();
  await expect(
    page.locator('[data-testid="stSidebar"]').getByText("Confirm pipeline"),
  ).toHaveCount(0);
  await expect(page.locator(".module-block")).toHaveCount(5);
  const sample = page.getByRole("button", {
    name: "+ sample_elasticisotr",
    exact: true,
  });
  const transfer = await page.evaluateHandle(() => new DataTransfer());
  await sample.dispatchEvent("dragstart", { dataTransfer: transfer });
  const slot = page.locator('[data-id="insertion-slot"]');
  await expect(slot).toBeVisible();
  const box = await slot.boundingBox();
  await slot.dispatchEvent("drop", {
    dataTransfer: transfer,
    clientX: box!.x + box!.width / 2,
    clientY: box!.y + box!.height / 2,
  });
  await expect(page.locator(".module-block")).toHaveCount(6);
  await expect(page.locator(".react-flow__edge")).toHaveCount(5);
  await page
    .getByRole("button", { name: "Remove sample_elasticisotr" })
    .click();
  await expect(page.locator(".module-block")).toHaveCount(5);
  await page
    .getByRole("button", { name: "+ capture_flux", exact: true })
    .click();
  await expect(page.locator(".module-block")).toHaveCount(6);
  await page.screenshot({
    path: "/tmp/vitess-flow-canvas.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toBeVisible();
  await expect(
    canvas.getByRole("heading", { name: "Confirmed pipeline" }),
  ).toBeVisible();
  await expect(canvas.getByText("Locked", { exact: true })).toBeVisible();
  await expect(canvas.locator(".module-block")).toHaveCount(6);
  await expect(canvas.locator(".react-flow__edge")).toHaveCount(5);
  await expect(canvas.getByText("capture_flux", { exact: true })).toBeVisible();
  await expect(
    canvas.locator(".module-palette, .remove, .confirm"),
  ).toHaveCount(0);
  await expect(page.getByText("Build pipeline", { exact: true })).toHaveCount(
    0,
  );
  await page.screenshot({
    path: "/tmp/vitess-flow-locked.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    canvas.getByRole("heading", { name: "Confirmed pipeline" }),
  ).toBeVisible();
  await expect(canvas.locator(".module-block")).toHaveCount(6);
  await expect(
    canvas.locator(".module-palette, .remove, .confirm"),
  ).toHaveCount(0);
  await expect(page.getByText("Build pipeline", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Start configuration" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toBeVisible();
  await expect(canvas).toBeVisible();
});

test("rejection preserves draft and a later dependency reopens the canvas", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("radiogroup", { name: "Starter topics" })
    .getByText("Build pipeline", { exact: true })
    .click();
  await page.getByRole("button", { name: "+ eval_elast", exact: true }).click();
  await page.getByText("Browser test controls").click();
  await page.getByRole("button", { name: "Reject next submission" }).click();
  await expect(
    page.getByText("Next submission will be rejected"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("order is not supported");
  await expect(page.locator(".module-block")).toHaveCount(6);
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toBeVisible();
  await page.getByText("Browser test controls").click();
  await page.getByRole("button", { name: "Simulate TOF dependency" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "requires screen before eval_elast",
  );
  await expect(
    page.getByRole("button", { name: "Remove eval_elast" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "requires screen before eval_elast",
  );
  await expect(
    page.getByRole("button", { name: "Confirm pipeline", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "+ screen", exact: true }).click();
  await page
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  const canvas = page.getByRole("region", { name: "Pipeline builder" });
  await expect(canvas.getByText("Locked", { exact: true })).toBeVisible();
  await expect(canvas.locator(".module-block strong")).toHaveText([
    "read_in",
    "guide",
    "writeout",
    "monitor_1d",
    "monitor_2d",
    "screen",
    "eval_elast",
  ]);
  await expect(
    canvas.locator(".module-palette, .remove, .confirm"),
  ).toHaveCount(0);
  await expect(page.getByText("Build pipeline", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toHaveCount(2);
});

test("sample preset has optional output modules and survives validation and refresh", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("radiogroup", { name: "Starter topics" })
    .getByText("Build pipeline", { exact: true })
    .click();
  const canvas = page.getByRole("region", { name: "Pipeline builder" });
  const preset = canvas.getByRole("combobox", { name: "Pipeline preset" });
  await expect(preset).toHaveValue("guide_test");
  await preset.selectOption("isotropic_sample_test");
  await expect(canvas.locator(".module-block strong")).toHaveText([
    "read_in",
    "guide",
    "sample_elasticisotr",
    "screen",
  ]);
  await expect(
    canvas.getByRole("button", { name: "Remove sample_elasticisotr" }),
  ).toHaveCount(0);
  for (const label of ["writeout", "monitor_1d", "monitor_2d"]) {
    await canvas
      .getByRole("button", { name: `+ ${label}`, exact: true })
      .click();
    await expect(canvas.locator(".module-block")).toHaveCount(5);
    await canvas.getByRole("button", { name: `Remove ${label}` }).click();
    await expect(canvas.locator(".module-block")).toHaveCount(4);
  }
  await preset.selectOption("guide_test");
  await expect(canvas.locator(".module-block strong")).toHaveText([
    "read_in",
    "guide",
    "writeout",
    "monitor_1d",
    "monitor_2d",
  ]);
  await preset.selectOption("isotropic_sample_test");
  await page.getByText("Browser test controls").click();
  await page.getByRole("button", { name: "Reject next submission" }).click();
  await expect(
    page.getByText("Next submission will be rejected"),
  ).toBeVisible();
  await canvas
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("order is not supported");
  await expect(preset).toHaveValue("isotropic_sample_test");
  await expect(canvas.locator(".module-block")).toHaveCount(4);
  await canvas
    .getByRole("button", { name: "Confirm pipeline", exact: true })
    .click();
  await expect(
    page.getByText("Configuration started for the confirmed pipeline."),
  ).toBeVisible();
  await expect(canvas.getByText("Locked", { exact: true })).toBeVisible();
  await expect(preset).toHaveCount(0);
  await expect(canvas.getByText(/Isotropic sample test ·/)).toBeVisible();
  await page.reload();
  await expect(canvas.getByText(/Isotropic sample test ·/)).toBeVisible();
  await expect(canvas.locator(".module-block strong")).toHaveText([
    "read_in",
    "guide",
    "sample_elasticisotr",
    "screen",
  ]);
  await page.screenshot({
    path: "/tmp/vitess-sample-preset.png",
    fullPage: true,
  });
});

for (const failure of ["lost response", "reload before planning"]) {
  test(`corrected pipeline recovers configuration after ${failure}`, async ({
    page,
  }) => {
    await page.goto("/");
    await page
      .getByRole("radiogroup", { name: "Starter topics" })
      .getByText("Build pipeline", { exact: true })
      .click();
    await page
      .getByRole("button", { name: "+ eval_elast", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Confirm pipeline", exact: true })
      .click();
    await expect(
      page.getByText("Configuration started for the confirmed pipeline."),
    ).toHaveCount(1);
    await page.getByText("Browser test controls").click();
    await page.getByRole("button", { name: "Simulate TOF dependency" }).click();
    await expect(page.getByRole("alert")).toContainText(
      "requires screen before eval_elast",
    );
    await page.getByRole("button", { name: "+ screen", exact: true }).click();
    await page.getByText("Browser test controls").click();
    await page
      .getByRole("button", {
        name:
          failure === "lost response"
            ? "Lose next confirmation response"
            : "Pause next handoff",
      })
      .click();
    await expect(
      page.getByText(
        failure === "lost response"
          ? "Next confirmation response will be lost"
          : "Next handoff will pause before planning",
      ),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Confirm pipeline", exact: true })
      .click();
    if (failure === "lost response") {
      await expect(
        page.getByRole("button", { name: "Start configuration" }),
      ).toBeVisible();
    } else {
      await expect(
        page.getByText("Handoff paused before planning"),
      ).toBeVisible();
    }
    await page.reload();
    await expect(
      page.getByText("Configuration started for the confirmed pipeline."),
    ).toHaveCount(1);
    await expect(page.getByText("Locked", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Confirm pipeline", exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Start configuration" }).click();
    await expect(
      page.getByText("Configuration started for the confirmed pipeline."),
    ).toHaveCount(2);
    await expect(
      page.getByRole("button", { name: "Start configuration" }),
    ).toHaveCount(0);
    await page.reload();
    await expect(
      page.getByText("Configuration started for the confirmed pipeline."),
    ).toHaveCount(2);
    await expect(
      page.getByRole("button", { name: "Start configuration" }),
    ).toHaveCount(0);
  });
}
