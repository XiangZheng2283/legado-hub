"""Pydantic models for Legado source parsing and LegadoHub data contracts."""

from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    bookId: str
    name: str
    author: str = ""
    coverUrl: str = ""
    intro: str = ""
    kind: str = ""
    lastChapter: str = ""
    wordCount: str = ""
    bookUrl: str = ""
    sourceId: str = ""
    sourceName: str = ""
    score: int = 0


class BookDetail(BaseModel):
    bookId: str
    name: str = ""
    author: str = ""
    coverUrl: str = ""
    intro: str = ""
    kind: str = ""
    lastChapter: str = ""
    wordCount: str = ""
    tocUrl: str = ""
    sourceId: str = ""
    sourceName: str = ""


class ChapterItem(BaseModel):
    chapterId: str
    title: str
    chapterUrl: str
    updateTime: str = ""
    sourceId: str = ""


class ChapterContent(BaseModel):
    chapterId: str
    title: str = ""
    content: str = ""


class SourceError(BaseModel):
    sourceId: str
    stage: str
    url: str = ""
    proxyUsed: bool = False
    error: str


class SearchResponse(BaseModel):
    implemented: bool = True
    keyword: str = ""
    page: int = 1
    items: list[SearchResultItem] = Field(default_factory=list)
    debug: dict = Field(default_factory=dict)


class BookResponse(BaseModel):
    implemented: bool = True
    data: BookDetail | None = None
    debug: dict = Field(default_factory=dict)


class TocResponse(BaseModel):
    implemented: bool = True
    bookId: str = ""
    chapters: list[ChapterItem] = Field(default_factory=list)
    debug: dict = Field(default_factory=dict)


class ChapterResponse(BaseModel):
    implemented: bool = True
    chapterId: str = ""
    title: str = ""
    content: str = ""
    debug: dict = Field(default_factory=dict)
