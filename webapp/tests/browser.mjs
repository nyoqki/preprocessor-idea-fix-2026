import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createConnection } from "node:net";
import { mkdir, writeFile } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.YASNO_DEMO_URL ?? "http://127.0.0.1:5183";
const live = process.env.YASNO_HTTP_URL ?? "http://127.0.0.1:5184";
const evidence = new URL(
    "../../docs/design/evidence/implementation/",
    import.meta.url,
);
await mkdir(evidence, { recursive: true });
const servers = [];
async function startServer(url, mock) {
    const child = spawn(
        process.execPath,
        [
            new URL("../node_modules/vite/bin/vite.js", import.meta.url)
                .pathname,
            "--host",
            "127.0.0.1",
            "--port",
            new URL(url).port,
            "--strictPort",
        ],
        {
            cwd: new URL("..", import.meta.url),
            env: { ...process.env, VITE_MOCK: mock ? "1" : "0" },
            stdio: "ignore",
        },
    );
    servers.push(child);
    for (let n = 0; n < 100; n++) {
        const ready = await new Promise((resolve) => {
            const socket = createConnection({
                host: "127.0.0.1",
                port: Number(new URL(url).port),
            });
            socket.once("connect", () => {
                socket.end();
                resolve(true);
            });
            socket.once("error", () => {
                socket.destroy();
                resolve(false);
            });
            socket.setTimeout(200, () => {
                socket.destroy();
                resolve(false);
            });
        });
        if (ready) {
            console.log("SERVER", url);
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, 100));
    }
    for (const server of servers) server.kill();
    throw new Error(`Vite did not start: ${url}`);
}
if (!process.env.YASNO_DEMO_URL) await startServer(base, true);
if (!process.env.YASNO_HTTP_URL) await startServer(live, false);
const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH ?? "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
});
const report = {
    passed: [],
    errors: [],
    buttons: [],
    contrastPairs: [],
    viewports: [],
};
const routes = [
    "/map",
    "/submissions",
    "/submissions/41",
    "/quiz/7",
    "/class",
    "/teacher",
];
const names = ["map", "history", "detail", "quiz", "materials", "teacher"];
async function context(theme = "light", width = 390, height = 844) {
    const ctx = await browser.newContext({
        viewport: { width, height },
        colorScheme: theme,
    });
    ctx.setDefaultTimeout(8000);
    ctx.setDefaultNavigationTimeout(15000);
    await ctx.route("https://st.max.ru/**", (route) => route.abort());
    return ctx;
}
let visit = 0;
async function open(page, route = "/map", options = {}) {
    const params = new URLSearchParams({
        role: "teacher",
        check: String(++visit),
        ...options,
    });
    await page.goto(`${base}/?${params}#${route}`);
    await page.locator(".screen h1").waitFor();
    if (options.scenario !== "loading")
        await page.waitForFunction(
            () => !document.querySelector('[aria-busy="true"]'),
        );
}
async function snap(page, name) {
    await page.screenshot({ path: new URL(`${name}.png`, evidence).pathname });
}
async function fits(page, label) {
    const sizes = await page.evaluate(() => ({
        width: innerWidth,
        document: document.documentElement.scrollWidth,
    }));
    assert(
        sizes.document <= sizes.width + 1,
        `${label}: page overflow ${JSON.stringify(sizes)}`,
    );
}
function rgb(hex) {
    return hex.match(/\w\w/g).map((v) => parseInt(v, 16));
}
function contrast(a, b) {
    const lum = (x) =>
        x
            .map((v) => {
                const n = v / 255;
                return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
            })
            .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
    const l = [lum(rgb(a)), lum(rgb(b))].sort((x, y) => y - x);
    return (l[0] + 0.05) / (l[1] + 0.05);
}
async function run(label, fn) {
    try {
        await fn();
        report.passed.push(label);
        console.log("PASS", label);
    } catch (e) {
        report.errors.push({ label, message: e.message });
        console.error("FAIL", label, e.message);
    }
}

try {
    for (const theme of ["light", "dark"]) {
        await run(`${theme}: six screens at five viewports`, async () => {
            const ctx = await context(theme);
            const page = await ctx.newPage();
            page.on("pageerror", (error) =>
                report.errors.push({
                    label: "JavaScript",
                    message: error.message,
                }),
            );
            for (const [width, height] of [
                [360, 800],
                [390, 844],
                [320, 568],
                [768, 1024],
                [1280, 800],
            ]) {
                await page.setViewportSize({ width, height });
                for (const [index, route] of routes.entries()) {
                    await open(page, route);
                    await fits(page, `${theme} ${width} ${route}`);
                    if (width === 390)
                        await snap(page, `${names[index]}-${theme}`);
                    if (width === 320 && route === "/quiz/7")
                        await snap(page, `quiz-320-${theme}`);
                    if (width === 1280 && route === "/teacher")
                        await snap(page, `teacher-wide-${theme}`);
                    await page.evaluate(() =>
                        window.scrollTo(
                            0,
                            document.documentElement.scrollHeight,
                        ),
                    );
                    const overlap = await page.evaluate(() => {
                        const nav = document.querySelector(".tabbar");
                        const main = document.querySelector("main");
                        return nav && main
                            ? main.getBoundingClientRect().bottom >
                                  nav.getBoundingClientRect().top + 1
                            : false;
                    });
                    assert.equal(
                        Boolean(overlap),
                        false,
                        `Bottom content under navigation: ${route}`,
                    );
                }
                report.viewports.push({ theme, width, height, screens: 6 });
                console.log("VIEWPORT", theme, width, height);
            }
            await page.setViewportSize({ width: 390, height: 844 });
            await open(page, "/map");
            const button = page.getByRole("button", { name: "Начать тест" });
            const style = async () =>
                button.evaluate((el) => ({
                    bg: getComputedStyle(el).backgroundColor,
                    label: getComputedStyle(el.querySelector(".action-content"))
                        .color,
                    icon: el.querySelector("svg")
                        ? getComputedStyle(el.querySelector("svg")).color
                        : null,
                    height: el.getBoundingClientRect().height,
                }));
            const def = await style();
            assert.equal(def.bg, "rgb(0, 102, 204)");
            assert.equal(def.label, "rgb(255, 255, 255)");
            await button.hover();
            assert.equal((await style()).bg, "rgb(0, 92, 191)");
            await page.mouse.down();
            assert.equal((await style()).bg, "rgb(0, 82, 173)");
            await page.mouse.move(1, 1);
            await page.mouse.up();
            await open(page, "/map", { scenario: "long" });
            await fits(page, "long map");
            await open(page, "/submissions/41", { scenario: "long" });
            await fits(page, "long formula");
            assert(
                await page
                    .locator(".line-math")
                    .first()
                    .evaluate((el) => el.scrollWidth > el.clientWidth),
            );
            assert.equal(
                await page.locator(".line-number").nth(1).innerText(),
                "2",
            );
            assert.equal(
                await page.locator(".photo-label").innerText(),
                "Шаг 2",
            );
            await open(page, "/teacher", { role: "student" });
            assert.equal(await page.locator(".tab").count(), 3);
            await page
                .getByRole("heading", { name: "Раздел для учителя" })
                .waitFor();
            await open(page, "/map", { role: "teacher" });
            assert.equal(await page.locator(".tab").count(), 4);
            for (const route of routes) {
                await open(page, route);
                await page.evaluate(() => {
                    document.querySelector(".yasno").style.zoom = "2";
                });
                await fits(page, `200% ${route}`);
            }
            await page.goto(`${base}/?catalog=1`);
            await page
                .getByRole("heading", { name: "Ясно · каталог" })
                .waitFor();
            await page.getByLabel("Тема", { exact: true }).selectOption(theme);
            await page.getByLabel("Поиск в каталоге").fill("дроби");
            const loading = page.getByRole("button", {
                name: "Отправка ответа",
            });
            const loadingStyle = await loading.evaluate((el) => ({
                bg: getComputedStyle(el).backgroundColor,
                label: getComputedStyle(el).color,
                spinner: getComputedStyle(el.querySelector(".action-spinner"))
                    .getPropertyValue("--MaxUi-Spinner_gradient-to")
                    .trim(),
                height: el.getBoundingClientRect().height,
                stops: [...el.querySelectorAll("stop")].map(
                    (s) => getComputedStyle(s).stopColor,
                ),
            }));
            assert.equal(loadingStyle.bg, "rgb(0, 102, 204)");
            assert.equal(loadingStyle.label, "rgb(255, 255, 255)");
            assert.equal(loadingStyle.spinner, "#fff");
            assert.equal(loadingStyle.height, def.height);
            const mainButton = page.getByRole("button", {
                name: "Основная кнопка",
            });
            assert.equal(
                await mainButton
                    .locator("svg")
                    .evaluate((el) => getComputedStyle(el).color),
                "rgb(255, 255, 255)",
            );
            const palette = await page.locator(".yasno").evaluate((el) => {
                const names = [
                    "canvas",
                    "surface",
                    "surface-raised",
                    "text-primary",
                    "text-secondary",
                    "text-muted",
                    "link",
                    "secondary-bg",
                    "secondary-label",
                    "secondary-hover",
                    "secondary-pressed",
                    "weak",
                    "weak-bg",
                    "improving",
                    "improving-bg",
                    "solid",
                    "solid-bg",
                    "control-border",
                ];
                const output = {};
                for (const name of names) {
                    const probe = document.createElement("span");
                    probe.style.color = `var(--yasno-${name})`;
                    el.append(probe);
                    output[name] = getComputedStyle(probe).color;
                    probe.remove();
                }
                return output;
            });
            const components = (value) => value.match(/[\d.]+/g).map(Number);
            const on = (fg, bg) => {
                const a = components(fg),
                    b = components(bg);
                return a
                    .slice(0, 3)
                    .map((v, i) =>
                        Math.round(v * (a[3] ?? 1) + b[i] * (1 - (a[3] ?? 1))),
                    );
            };
            const hex = (values) =>
                values.map((v) => v.toString(16).padStart(2, "0")).join("");
            for (const [fg, bg, min] of [
                ["text-primary", "canvas", 4.5],
                ["text-secondary", "surface-raised", 4.5],
                ["text-muted", "canvas", 4.5],
                ["text-muted", "surface-raised", 4.5],
                ["link", "surface-raised", 4.5],
                ["secondary-label", "secondary-bg", 4.5],
                ["secondary-label", "secondary-hover", 4.5],
                ["secondary-label", "secondary-pressed", 4.5],
                ["weak", "weak-bg", 4.5],
                ["improving", "improving-bg", 4.5],
                ["solid", "solid-bg", 4.5],
                ["control-border", "surface-raised", 3],
            ]) {
                const ratio = contrast(
                    hex(on(palette[fg], palette[bg])),
                    hex(components(palette[bg]).slice(0, 3)),
                );
                assert(ratio >= min, `${theme} ${fg}/${bg} ${ratio}`);
                report.contrastPairs.push({
                    theme,
                    foreground: fg,
                    background: bg,
                    ratio,
                });
            }
            report.buttons.push({
                theme,
                default: def,
                loading: loadingStyle,
                contrasts: {
                    default: contrast("ffffff", "0066cc"),
                    hover: contrast("ffffff", "005cbf"),
                    pressed: contrast("ffffff", "0052ad"),
                },
            });
            await mainButton.focus();
            assert.equal(
                await mainButton.evaluate(
                    (el) => getComputedStyle(el).outlineStyle,
                ),
                "solid",
            );
            await page.keyboard.press("Enter");
            await page.getByText("Нажатий: 1", { exact: true }).waitFor();
            await page
                .getByLabel("Тема", { exact: true })
                .selectOption(theme === "light" ? "dark" : "light");
            assert.equal(
                await page.getByLabel("Поиск в каталоге").inputValue(),
                "дроби",
            );
            assert.equal(
                await mainButton.evaluate((el) => getComputedStyle(el).color),
                "rgb(255, 255, 255)",
            );
            await page
                .getByLabel("Тема", { exact: true })
                .selectOption("system");
            await page.emulateMedia({
                colorScheme: theme === "light" ? "dark" : "light",
            });
            await page.waitForFunction(
                (expected) =>
                    document.documentElement.dataset.scheme === expected,
                theme === "light" ? "dark" : "light",
            );
            await page.emulateMedia({ reducedMotion: "reduce" });
            assert.equal(
                await page
                    .locator(".skeleton")
                    .first()
                    .evaluate((el) => getComputedStyle(el).animationName),
                "none",
            );
            await page.getByLabel("Тема", { exact: true }).selectOption(theme);
            await snap(page, `catalog-${theme}`);
            await ctx.close();
        });
        await run(`${theme}: empty/error/recovery/detail states`, async () => {
            const ctx = await context(theme);
            const page = await ctx.newPage();
            for (const route of [
                "/map",
                "/submissions",
                "/class",
                "/teacher",
            ]) {
                await open(page, route, { scenario: "empty" });
                assert(await page.locator(".state-title").count());
                await fits(page, `empty ${route}`);
            }
            await open(page, "/map", { scenario: "empty" });
            await snap(page, `empty-${theme}`);
            for (const route of routes) {
                await open(page, route, { scenario: "error" });
                console.log("ERROR STATE", theme, route);
                const retry = page.getByRole("button", {
                    name: "Повторить загрузку",
                });
                assert(await retry.count());
                await retry.last().click();
                await page.waitForFunction(
                    () => !document.querySelector('.state[role="alert"]'),
                );
                await fits(page, `recovery ${route}`);
            }
            await open(page, "/map", { scenario: "quiz-error" });
            assert.equal(await page.locator(".topic-card").count(), 4);
            await snap(page, `quiz-error-${theme}`);
            await page
                .getByRole("button", { name: "Повторить загрузку" })
                .click();
            await page.getByRole("button", { name: "Начать тест" }).waitFor();
            await open(page, "/map", { scenario: "no-test" });
            assert.equal(await page.locator(".cta-card").count(), 0);
            assert.equal(await page.locator(".topic-card").count(), 4);
            for (const [scenario, label] of Object.entries({
                correct: "Решение проверено",
                review: "Нужно пояснить шаг",
                incomplete: "Решение ещё не закончено",
                unknown: "Результат проверки недоступен",
                queued: "Фото в очереди",
                processing: "Разбираем решение",
                confirmation: "Нужно уточнить запись",
                failed: "Не удалось разобрать фото",
            })) {
                await open(page, "/submissions/41", { scenario });
                await page
                    .getByRole("heading", { name: label, exact: true })
                    .waitFor();
                if (scenario !== "correct")
                    assert.equal(
                        await page
                            .getByText("В проверенных шагах ошибок не найдено.")
                            .count(),
                        0,
                    );
                await fits(page, scenario);
            }
            await open(page, "/submissions/41", { scenario: "photo-error" });
            await page
                .getByRole("button", { name: "Загрузить фото" })
                .waitFor();
            assert.equal(await page.locator(".line").count(), 4);
            await snap(page, `photo-error-${theme}`);
            await page.getByRole("button", { name: "Загрузить фото" }).click();
            await page
                .getByRole("button", { name: "Загрузить фото" })
                .waitFor();
            await open(page, "/submissions/41", { scenario: "processing" });
            await ctx.setOffline(true);
            await page
                .getByRole("button", { name: "Обновить состояние" })
                .click();
            await page
                .getByText(
                    "Не удалось обновить разбор. Предыдущий результат остаётся на экране.",
                )
                .waitFor();
            assert.equal(await page.locator(".line").count(), 4);
            await ctx.setOffline(false);
            await page
                .getByRole("button", { name: "Повторить загрузку" })
                .click();
            await page
                .getByRole("button", { name: "Обновить состояние" })
                .waitFor();
            for (const route of ["/class", "/teacher"]) {
                await open(page, route, { scenario: "no-class" });
                await page
                    .getByRole("heading", {
                        name:
                            route === "/class"
                                ? "Класс пока не подключён"
                                : "Класс не подключён",
                    })
                    .waitFor();
            }
            await open(page, "/class");
            await page.getByRole("searchbox").fill("несуществующая тема");
            await page
                .getByRole("heading", { name: "Совпадений нет" })
                .waitFor();
            // Clearing must reset both the visible value and the result query.
            await page.locator(".search-clear").click();
            await page
                .getByRole("heading", { name: "Конспект: теорема Виета" })
                .waitFor();
            for (const route of ["/class", "/submissions"]) {
                await open(page, route, { scenario: "pagination-error" });
                const firstCount = await page
                    .locator(
                        route === "/class" ? ".material" : ".history-title",
                    )
                    .count();
                assert.equal(firstCount, 2);
                await page
                    .getByRole("button", { name: "Показать ещё" })
                    .click();
                await page.getByRole("alert").waitFor();
                assert.equal(
                    await page
                        .locator(
                            route === "/class" ? ".material" : ".history-title",
                        )
                        .count(),
                    2,
                );
                if (route === "/class")
                    await snap(page, `pagination-error-${theme}`);
                await page
                    .getByRole("button", { name: "Повторить загрузку" })
                    .click();
                await page.waitForFunction(
                    (selector) =>
                        document.querySelectorAll(selector).length > 2,
                    route === "/class" ? ".material" : ".history-title",
                );
            }
            for (const [scenario, label] of [
                ["auth", "Открой Ясно в MAX"],
                ["forbidden", "Раздел для учителя"],
                ["not-found", "Разбор недоступен"],
            ]) {
                await open(page, "/submissions/41", { scenario });
                await page.getByRole("heading", { name: label }).waitFor();
            }
            await open(page, "/quiz/7", { scenario: "not-found" });
            await page
                .getByRole("heading", { name: "Тест недоступен" })
                .waitFor();
            await open(page, "/class", { scenario: "loading" });
            await page.locator('[aria-busy="true"]').first().waitFor();
            await snap(page, `loading-${theme}`);
            await ctx.close();
        });
        await run(
            `${theme}: quiz answers, recovery, exit, reload, completion`,
            async () => {
                const ctx = await context(theme);
                const page = await ctx.newPage();
                await open(page, "/quiz/7");
                await page.locator(".choice").nth(0).dblclick();
                await page
                    .getByText("Ответ не совпал", { exact: true })
                    .waitFor();
                await page
                    .getByText("Верный ответ: 1", { exact: true })
                    .waitFor();
                await snap(page, `answer-wrong-${theme}`);
                assert.equal(
                    await page.locator('.choice[aria-pressed="true"]').count(),
                    1,
                );
                await page
                    .getByRole("button", { name: "Следующий вопрос" })
                    .click();
                await page
                    .getByRole("button", { name: "Назад", exact: true })
                    .click();
                await page
                    .getByRole("button", { name: "Продолжить тест" })
                    .waitFor();
                await page
                    .getByRole("button", { name: "Продолжить тест" })
                    .click();
                await page
                    .getByText("Вопрос 2 из 5", { exact: true })
                    .waitFor();
                await page.reload();
                await page
                    .getByText("Вопрос 2 из 5", { exact: true })
                    .waitFor();
                for (const index of [2, 1, 2, 1]) {
                    await page.locator(".choice").nth(index).click();
                    await page.getByText("Верно", { exact: true }).waitFor();
                    await page
                        .getByRole("button", {
                            name: /Следующий вопрос|Посмотреть результат/,
                        })
                        .click();
                }
                await page
                    .getByRole("heading", { name: "Тест завершён" })
                    .waitFor();
                await page.getByText("4 из 5", { exact: true }).waitFor();
                await snap(page, `completed-${theme}`);
                await page.reload();
                await page.getByText("4 из 5", { exact: true }).waitFor();
                for (const scenario of ["answer-error", "answer-saved"]) {
                    await open(page, "/quiz/7", { scenario });
                    await page.locator(".choice").nth(1).click();
                    await page
                        .getByRole("button", { name: "Проверить и повторить" })
                        .waitFor();
                    assert.equal(
                        await page.getByText("Верно", { exact: true }).count(),
                        0,
                    );
                    await snap(page, `${scenario}-${theme}`);
                    await page
                        .getByRole("button", { name: "Проверить и повторить" })
                        .click();
                    await page.getByText("Верно", { exact: true }).waitFor();
                    if (scenario === "answer-saved")
                        await page
                            .getByText("Показан ранее сохранённый ответ.")
                            .waitFor();
                }
                await open(page, "/quiz/7", { scenario: "expired" });
                await page
                    .getByRole("heading", { name: "Срок теста истёк" })
                    .waitFor();
                assert.equal(await page.locator(".choice").count(), 0);
                await ctx.setOffline(true);
                await page.getByText(/Нет интернета/).waitFor();
                await ctx.setOffline(false);
                await ctx.close();
            },
        );
    }
    await run(
        "real HTTP client: ambiguous POST, saved answer, expiry, auth and deep links",
        async () => {
            const ctx = await context();
            const page = await ctx.newPage();
            let chosen = null;
            let expired = false;
            let posts = 0;
            let expireOnAnswer = false;
            const profile = {
                id: 1,
                first_name: "Ученик",
                last_name: null,
                role: "student",
                grade: 9,
                consent_status: "granted",
                school_class: null,
            };
            const quiz = () => ({
                id: 7,
                reason: "review",
                status: expired
                    ? "expired"
                    : chosen === null
                      ? "active"
                      : "completed",
                created_at: new Date().toISOString(),
                total: 1,
                answered: chosen === null ? 0 : 1,
                correct: chosen === 1 ? 1 : 0,
                topic_titles: ["Дроби"],
                items: [
                    {
                        id: 100,
                        position: 0,
                        topic_code: "fractions",
                        topic_title: "Дроби",
                        prompt: "2/3 + 1/6 = ?",
                        choices: [
                            { index: 0, text: "1/2" },
                            { index: 1, text: "5/6" },
                        ],
                        from_gap_map: true,
                        answered_index: chosen,
                        correct_index: chosen === null ? null : 1,
                        is_correct: chosen === null ? null : chosen === 1,
                    },
                ],
            });
            await ctx.route("**/api/v1/**", async (route) => {
                const path = new URL(route.request().url()).pathname;
                if (path.endsWith("/me"))
                    return route.fulfill({ json: profile });
                if (path.endsWith("/answer")) {
                    posts++;
                    if (expireOnAnswer) {
                        expired = true;
                        return route.fulfill({
                            status: 409,
                            json: { detail: "quiz_closed" },
                        });
                    }
                    chosen = 1;
                    return route.abort("connectionreset");
                }
                if (path.endsWith("/quizzes/7"))
                    return route.fulfill({ json: quiz() });
                return route.fulfill({
                    status: 404,
                    json: { detail: "not_found" },
                });
            });
            await page.goto(`${live}/?startapp=quiz_7`);
            await page.locator(".choice").nth(1).click();
            await page
                .getByRole("button", { name: "Проверить и повторить" })
                .waitFor();
            assert.equal(posts, 2); // Existing HTTP retry is idempotent server-side.
            await page
                .getByRole("button", { name: "Проверить и повторить" })
                .click();
            await page.getByText("Показан ранее сохранённый ответ.").waitFor();
            assert.equal(posts, 2);
            await page
                .getByRole("button", { name: "Посмотреть результат" })
                .click();
            await page.getByText("1 из 1", { exact: true }).waitFor();
            chosen = null;
            expired = false;
            expireOnAnswer = true;
            await page.reload();
            await page.locator(".choice").nth(1).click();
            await page
                .getByRole("button", { name: "Проверить и повторить" })
                .click();
            await page
                .getByRole("heading", { name: "Срок теста истёк" })
                .waitFor();
            await page
                .getByRole("button", { name: "Назад", exact: true })
                .click();
            assert(page.url().endsWith("#/map"));
            await ctx.unroute("**/api/v1/**");
            await ctx.route("**/api/v1/**", (route) =>
                route.fulfill({
                    status: 401,
                    json: { detail: "unauthorized" },
                }),
            );
            await page.goto(live);
            await page
                .getByRole("heading", { name: "Открой Ясно в MAX" })
                .waitFor();
            await ctx.close();
        },
    );
    await run(
        "native BackButton lifecycle with feature detection",
        async () => {
            const ctx = await context();
            await ctx.addInitScript(() => {
                const handlers = new Set();
                window.__back = { handlers, shown: false };
                window.WebApp = {
                    initData: "synthetic",
                    platform: "android",
                    ready() {},
                    getViewportSize: async () => ({
                        width: "390",
                        height: "844",
                    }),
                    BackButton: {
                        show() {
                            window.__back.shown = true;
                        },
                        hide() {
                            window.__back.shown = false;
                        },
                        onClick(fn) {
                            handlers.add(fn);
                        },
                        offClick(fn) {
                            handlers.delete(fn);
                        },
                    },
                };
            });
            const page = await ctx.newPage();
            await open(page, "/submissions/41");
            assert.equal(
                await page
                    .getByRole("button", { name: "Назад", exact: true })
                    .count(),
                0,
            );
            assert.equal(
                await page.evaluate(() => window.__back.handlers.size),
                1,
            );
            await page.evaluate(() => [...window.__back.handlers][0]());
            await page
                .getByRole("heading", { name: "Разборы", exact: true })
                .waitFor();
            assert.equal(
                await page.evaluate(() => window.__back.handlers.size),
                0,
            );
            assert.equal(await page.evaluate(() => window.__back.shown), false);
            await ctx.close();
        },
    );
} finally {
    await browser.close();
    for (const server of servers) server.kill();
    await writeFile(
        new URL("browser-report.json", evidence),
        JSON.stringify(report, null, 2),
    );
}
console.log(
    JSON.stringify(
        { passed: report.passed.length, errors: report.errors },
        null,
        2,
    ),
);
if (report.errors.length) process.exitCode = 1;
