import { expect, test } from '@playwright/test'

test('home shows the forecast and any area on the map', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('AirAware forecast')).toBeVisible()
  await expect(page.getByText('hour by hour')).toBeVisible()
  await page.locator('.leaflet-container').first().click({ position: { x: 200, y: 200 } })
  await expect(page.getByText('forecast for this area')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/station(s)? within 12 km/)).toBeVisible()
})

test('public pages load', async ({ page }) => {
  for (const [path, text] of [['/explore', 'When in the day is the air cleanest?'], ['/science', 'The science'],
    ['/track-record', 'Track record'], ['/about', 'Know your air, a week ahead'], ['/compare', 'Compare areas']]) {
    await page.goto(path)
    await expect(page.getByText(text).first()).toBeVisible()
  }
})

test('sign up, save a place, set an alert, sign out', async ({ page }) => {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`
  await page.goto('/signup')
  await page.getByLabel('Name').fill('E2E Tester')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('e2e-password-123')
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
