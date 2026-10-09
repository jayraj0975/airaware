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
