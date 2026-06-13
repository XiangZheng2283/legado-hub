import { describe, it, expect, vi } from "vitest"
import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ChapterReviewDialog, ReviewList } from "./SearchJobs"

function makeReviews(overrides: any = {}) {
  const list = (count: number, prefix: string) =>
    Array.from({ length: count }, (_, i) => ({
      id: `${prefix}-${i}`,
      userName: `user-${i}`,
      content: `content-${i}`,
      likeNum: i,
      replyCount: 0,
    }))
  return {
    paragraphs: {},
    chapterEnd: [],
    chapterEndHot: [],
    authorReviews: [],
    summary: { totalReviews: 0 },
    ...overrides,
  }
}

describe("ReviewList", () => {
  it("renders first 10 reviews by default and expands to show more", async () => {
    const reviews = Array.from({ length: 15 }, (_, i) => ({
      id: `r-${i}`,
      userName: `user-${i}`,
      content: `review content ${i}`,
      likeNum: i,
      replyCount: 0,
    }))
    render(<ReviewList reviews={reviews} limit={10} />)
    expect(screen.getAllByText(/review content/).length).toBe(10)
    const expandBtn = screen.getByRole("button", { name: /展开更多 5 条/ })
    await userEvent.click(expandBtn)
    await waitFor(() => expect(screen.getAllByText(/review content/).length).toBe(15))
    expect(screen.getByRole("button", { name: /收起/ })).toBeInTheDocument()
  })

  it("expands incrementally in steps of 10", async () => {
    const reviews = Array.from({ length: 32 }, (_, i) => ({
      id: `r-${i}`,
      userName: `user-${i}`,
      content: `review content ${i}`,
      likeNum: i,
      replyCount: 0,
    }))
    render(<ReviewList reviews={reviews} limit={10} step={10} />)
    expect(screen.getAllByText(/review content/).length).toBe(10)

    await userEvent.click(screen.getByRole("button", { name: /展开更多 10 条/ }))
    await waitFor(() => expect(screen.getAllByText(/review content/).length).toBe(20))

    await userEvent.click(screen.getByRole("button", { name: /展开更多 10 条/ }))
    await waitFor(() => expect(screen.getAllByText(/review content/).length).toBe(30))

    await userEvent.click(screen.getByRole("button", { name: /展开更多 2 条/ }))
    await waitFor(() => expect(screen.getAllByText(/review content/).length).toBe(32))

    expect(screen.getByRole("button", { name: /收起/ })).toBeInTheDocument()
  })
})

describe("ChapterReviewDialog", () => {
  it("defaults to paragraph tab when chapter-end is empty but paragraphs exist", () => {
    const reviews = makeReviews({
      paragraphs: {
        "3": Array.from({ length: 5 }, (_, i) => ({
          id: `p-${i}`,
          userName: `u-${i}`,
          content: `para-review-${i}`,
          likeNum: i,
          replyCount: 0,
        })),
      },
      summary: { totalReviews: 5, totalParagraphs: 1, paragraphStats: { "3": 5 } },
    })
    render(
      <ChapterReviewDialog
        reviews={reviews}
        loading={false}
        error={null}
        open={true}
        onOpenChange={vi.fn()}
      />
    )
    expect(screen.getByRole("tabpanel")).toHaveAttribute("data-state", "active")
    expect(screen.getByText("第 3 段")).toBeInTheDocument()
  })

  it("defaults to chapter tab when chapter-end reviews exist", () => {
    const reviews = makeReviews({
      chapterEnd: Array.from({ length: 12 }, (_, i) => ({
        id: `c-${i}`,
        userName: `u-${i}`,
        content: `chapter-review-${i}`,
        likeNum: i,
        replyCount: 0,
      })),
      summary: { totalReviews: 12, chapterEndCount: 12 },
    })
    render(
      <ChapterReviewDialog
        reviews={reviews}
        loading={false}
        error={null}
        open={true}
        onOpenChange={vi.fn()}
      />
    )
    expect(screen.getByText("全部章评")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /展开更多 2 条/ })).toBeInTheDocument()
  })

  it("scroll container is present in the dialog", () => {
    const reviews = makeReviews({
      chapterEnd: Array.from({ length: 20 }, (_, i) => ({
        id: `c-${i}`,
        userName: `u-${i}`,
        content: `chapter-review-${i}`,
        likeNum: i,
        replyCount: 0,
      })),
      summary: { totalReviews: 20, chapterEndCount: 20 },
    })
    render(
      <ChapterReviewDialog
        reviews={reviews}
        loading={false}
        error={null}
        open={true}
        onOpenChange={vi.fn()}
      />
    )
    const scrollContainer = document.body.querySelector("[data-testid='review-scroll-container']")
    expect(scrollContainer).toBeTruthy()
  })
})
