import { expect, test } from '@playwright/test'

test('home shows the forecast and any area on the map', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.hero .reading-num')).toHaveText(/^\d+$/)
  await expect(page.getByText('hour by hour')).toBeVisible()
  await page.locator('.leaflet-container').first().click({ position: { x: 200, y: 200 } })
  await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/station(s)? within 12 km/)).toBeVisible()
})

test('public pages load', async ({ page }) => {
  for (const [path, text] of [['/explore', 'When in the day is the air cleanest?'], ['/science', 'The science'],
    ['/track-record', 'Track record'], ['/about', 'Know your air, a week ahead'], ['/compare', 'Compare areas']]) {
    await page.goto(path)
    await expect(page.locator('main').getByText(text).first()).toBeVisible()  // not the collapsed phone menu
  }
})

test('sign up, save a place, set an alert, sign out', async ({ page }) => {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
  await page.goto('/signup')
  await page.getByLabel('Name').fill('E2E Tester')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('e2e-password-123')
  await page.getByLabel('I am 18 or older').check()
  await page.getByLabel(/I agree to the Terms/).check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Hi E2E' })).toBeVisible()

  await page.getByRole('button', { name: '+ Add a place' }).click()
  await page.locator('.add-place .leaflet-container').click({ position: { x: 150, y: 150 } })
  await page.getByPlaceholder('Name, e.g. Home').fill('Home')
  await page.getByRole('button', { name: 'Save place' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
  await page.getByRole('button', { name: 'Add alert' }).click()
  await expect(page.getByText('Warn me at AQI')).toBeVisible()

  await page.goto('/admin')  // not an admin: sent home
  await expect(page).toHaveURL(/\/$/)

  const menu = page.locator('.menu-btn')
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible()
})

test('wrong password is refused', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('Email').fill('nobody@example.com')
  await page.getByLabel('Password').fill('not-the-password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('Wrong email or password.')).toBeVisible()
})

test('a shared link opens that area, switching city if needed', async ({ page }) => {
  await page.goto('/?lat=19.06&lon=72.836')  // Bandra, Mumbai
  await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('.cities .on')).toHaveText('Mumbai')
  await expect(page).toHaveURL(/lat=19\.06/)
})

test('legal pages and the rights form', async ({ page }) => {
  await page.goto('/privacy')
  await expect(page.getByRole('heading', { name: 'Privacy Notice' })).toBeVisible()
  await expect(page.getByText('Data Protection Board of India').first()).toBeVisible()
  await page.goto('/terms')
  await expect(page.getByRole('heading', { name: 'Terms of use' })).toBeVisible()
  await page.goto('/rights')
  await page.getByLabel('Your email (we reply here)').fill('e2e-rights@example.com')
  await page.getByLabel('Tell us more').fill('Please send me a summary of my data.')
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByText(/within 30 days/).first()).toBeVisible()
})

// ---------- regressions: location, two-step sign-in, dialogs inside forms ----------

test.describe('use my location', () => {
  test.use({ permissions: ['geolocation'], geolocation: { latitude: 18.5089, longitude: 73.8077 } })

  test('inside Pune: shows that area', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Use my location' }).click()
    await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
    await expect(page).toHaveURL(/lat=18\.5089/)
    // On a phone the result is below the map: it must be brought into view, or the tap seems to do nothing.
    await expect(page.locator('#your-area')).toBeInViewport()
    await expect(page.getByText('only knows roughly')).toHaveCount(0)
  })

  test('rough position (no GPS, e.g. a laptop): shows the spot and says it may be off', async ({ page, context }) => {
    await context.setGeolocation({ latitude: 18.5089, longitude: 73.8077, accuracy: 9000 })
    await page.goto('/')
    await page.getByRole('button', { name: 'Use my location' }).click()
    await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByText(/only knows roughly where you are, to within about 9\.0 km/)).toBeVisible()
  })

  test('no precise fix in time: falls back to the rough position', async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => {
      navigator.geolocation.getCurrentPosition = (ok, err, opts) => opts?.enableHighAccuracy
        ? err!({ code: 3 } as GeolocationPositionError)
        : ok({ coords: { latitude: 18.5089, longitude: 73.8077, accuracy: 500 } } as GeolocationPosition)
    })
    await page.getByRole('button', { name: 'Use my location' }).click()
    await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  })

  test('outside the covered area: says how far and offers the nearest city', async ({ page, context }) => {
    await context.setGeolocation({ latitude: 18.6129, longitude: 74.5695 })
    await page.goto('/')
    await page.getByRole('button', { name: 'Use my location' }).click()
    await expect(page.getByText(/about \d+ km from Pune/)).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: "Show Pune's forecast" }).click()
    await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  })

  test('blocked: explains how to allow it', async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => { navigator.geolocation.getCurrentPosition = (_ok, err) => err!({ code: 1 } as GeolocationPositionError) })
    await page.getByRole('button', { name: 'Use my location' }).click()
    await expect(page.getByText('Location is blocked for this site')).toBeVisible()
  })
})

/** RFC 6238 code from a base32 key, the way an authenticator app computes it. */
async function totp(secret: string, offset = 0): Promise<string> {
  const { createHmac } = await import('node:crypto')
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const ch of secret.replace(/\s/g, '')) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + offset))
  const h = createHmac('sha1', key).update(counter).digest()
  const o = h[h.length - 1] & 15
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, '0')
}

test('two-step sign-in: set up from the dashboard, then sign in with a code; delete the account', async ({ page }) => {
  const email = `e2e-2fa-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
  const password = 'e2e-two-step-pass'
  await page.goto('/signup')
  await page.getByLabel('Name').fill('Two Step')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByLabel('I am 18 or older').check()
  await page.getByLabel(/I agree to the Terms/).check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: /^Hi Two/ })).toBeVisible()

  await page.getByRole('button', { name: 'Set up two-step sign-in' }).click()
  await page.getByRole('dialog').getByLabel('Your password').fill(password)
  await page.getByRole('dialog').getByRole('button', { name: 'Continue' }).click()
  const key = (await page.locator('.key').innerText()).trim()
  await expect(page).not.toHaveURL(/\/me\?/)  // a nested form once submitted the page instead
  await page.getByLabel('6-digit code').fill(await totp(key))
  await page.getByLabel('6-digit code').press('Enter')
  await expect(page.locator('.two-step.on')).toBeVisible()

  const menu = page.locator('.menu-btn')
  if (await menu.isVisible()) await menu.click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByLabel(/6-digit code/).fill(await totp(key, 1))
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: /^Hi Two/ })).toBeVisible()

  await page.getByRole('button', { name: 'Delete my account' }).click()
  await page.getByRole('dialog').getByLabel('Your password').fill(password)
  await page.getByRole('dialog').getByRole('button', { name: 'Delete for good' }).click()
  await expect(page.getByText('Your account and everything in it has been deleted.')).toBeVisible()
})

// ---------- pollution reports, the admin console, honest science, password help ----------

async function signUp(page: import('@playwright/test').Page, name: string, password: string) {
  const email = `e2e-${name.toLowerCase().replace(/\W+/g, '-')}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
  await page.goto('/signup')
  await page.getByLabel('Name').fill(name)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByLabel('I am 18 or older').check()
  await page.getByLabel(/I agree to the Terms/).check()
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: new RegExp(`^Hi ${name.split(' ')[0]}`) })).toBeVisible()
  return email
}

test('report pollution from the map, then correct and withdraw it from the dashboard', async ({ page }) => {
  await signUp(page, 'Reporter', 'e2e-reporter-pass')
  await page.goto('/?lat=18.50740&lon=73.80770')
  await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Report pollution' }).click()
  await page.getByLabel('What is it?').selectOption('construction')
  await page.getByLabel('Note (optional)').fill('Dust from a building site')
  await page.getByRole('button', { name: 'Send report' }).click()
  await expect(page.getByText(/will show on the map once a moderator approves it/)).toBeVisible()

  await page.goto('/me')
  const row = page.locator('tr', { hasText: 'Dust from a building site' })
  await expect(row.getByText('pending')).toBeVisible()
  await row.getByRole('button', { name: 'Edit' }).click()
  await page.getByRole('dialog').getByLabel('What is it?').selectOption('burning')
  await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
  await expect(row.getByText('Garbage or leaf burning')).toBeVisible()
  await row.getByRole('button', { name: 'Withdraw' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Withdraw' }).click()
  await expect(page.locator('tr', { hasText: 'Dust from a building site' })).toHaveCount(0)
})

test('an admin moderates with filters, sees report statistics and downloads a backup', async ({ page, browser }, info) => {
  // A citizen files a report in Mumbai (a unique note: desktop and phone runs share one test database).
  const note = `Idling buses at the depot ${info.project.name} ${Date.now()}`
  const citizen = await browser.newPage()
  await signUp(citizen, 'Citizen', 'e2e-citizen-pass')
  const r = await citizen.request.post('/api/reports', { headers: { 'X-AirAware': '1' }, data: { lat: 19.0596, lon: 72.8295, kind: 'traffic', note } })
  expect(r.status()).toBe(201)
  await citizen.close()

  // An admin: promoted from the server's command line (the only way), then two-step sign-in, which the console needs.
  const password = 'e2e-admin-pass-1'
  const email = await signUp(page, 'Moderator', password)
  const { execFileSync } = await import('node:child_process')
  execFileSync('python', ['-m', 'airaware.server.manage', 'make-admin', email], { cwd: '..', env: { ...process.env, AIRAWARE_DB: '/tmp/airaware-e2e.db' } })
  await page.reload()
  await page.getByRole('button', { name: 'Set up two-step sign-in' }).click()
  await page.getByRole('dialog').getByLabel('Your password').fill(password)
  await page.getByRole('dialog').getByRole('button', { name: 'Continue' }).click()
  const key = (await page.locator('.key').innerText()).trim()
  await page.getByLabel('6-digit code').fill(await totp(key))
  await page.getByLabel('6-digit code').press('Enter')
  await expect(page.locator('.two-step.on')).toBeVisible()

  await page.goto('/admin')
  await page.getByRole('button', { name: 'Reports', exact: true }).click()
  const item = page.locator('.moderation li', { hasText: note })
  await expect(item).toBeVisible()
  await item.getByRole('button', { name: 'Approve' }).click()
  await expect(page.locator('.moderation li', { hasText: note })).toHaveCount(0)  // left the pending queue
  await page.locator('.filters').getByRole('button', { name: 'approved', exact: true }).click()
  await page.locator('.filters select').nth(1).selectOption('Mumbai')
  await expect(page.locator('.moderation li', { hasText: note })).toBeVisible()
  await page.locator('.filters select').nth(1).selectOption('Pune')
  await expect(page.locator('.moderation li', { hasText: note })).toHaveCount(0)
  await expect(page.getByText('Reports, last 90 days')).toBeVisible()
  await expect(page.locator('.card', { hasText: 'Reports, last 90 days' }).getByRole('cell', { name: 'Heavy traffic or idling' })).toBeVisible()

  await page.getByRole('button', { name: 'Data & jobs', exact: true }).click()
  await page.getByRole('button', { name: 'Download a backup' }).click()
  const download = page.waitForEvent('download')
  await page.getByRole('dialog').getByRole('button', { name: 'Download' }).click()
  expect((await download).suggestedFilename()).toMatch(/^airaware-\d{4}-\d{2}-\d{2}\.db$/)
})

test('the science page tells the honest story', async ({ page }) => {
  await page.goto('/science')
  await expect(page.getByRole('heading', { name: 'How we keep the test honest' })).toBeVisible()
  await expect(page.getByText(/Station history only/).first()).toBeVisible()
  await expect(page.getByText(/Upper bound/).first()).toBeVisible()
  await expect(page.getByText(/significant/).first()).toBeVisible()
})

test('forgot password answers the same whether or not the account exists', async ({ page }) => {
  await page.goto('/forgot')
  await page.getByLabel('Email').fill('nobody-here@example.com')
  await page.getByRole('button', { name: /send/i }).click()
  await expect(page.getByText(/if an account|if that email/i)).toBeVisible()
})

test('no page scrolls sideways on a phone', async ({ page }, info) => {
  test.skip(info.project.name !== 'phone', 'phone layout only')
  await signUp(page, 'Narrow', 'e2e-narrow-pass')
  await page.request.post('/api/reports', { headers: { 'X-AirAware': '1' }, data: { lat: 18.52, lon: 73.85, kind: 'burning', note: 'a row in the reports table' } })
  for (const path of ['/', '/explore', '/compare', '/science', '/track-record', '/about', '/privacy', '/terms', '/rights', '/me', '/admin']) {
    await page.goto(path)
    await page.waitForLoadState('networkidle')
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(over, path).toBeLessThanOrEqual(0)
  }
})
