import sqlite3
from pathlib import Path

import pandas as pd
DB_FILE = "blogs.db"


# ==========================================
# Connection
# ==========================================

def get_connection():

    conn = sqlite3.connect(
        DB_FILE
    )

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


# ==========================================
# Initialize Database
# ==========================================

def init_db():

    conn = get_connection()
    cursor = conn.cursor()

    # ------------------------
    # Blogs
    # ------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blogs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        filename TEXT UNIQUE,

        original_title TEXT,
        display_title TEXT,

        created_at TEXT,

        word_count INTEGER DEFAULT 0,
        image_count INTEGER DEFAULT 0,
        evidence_count INTEGER DEFAULT 0,

        runtime REAL DEFAULT 0,

        pinned INTEGER DEFAULT 0
    )
    """)

    # ------------------------
    # Categories
    # ------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE COLLATE NOCASE
    )
    """)

    # ------------------------
    # Blog Categories
    # ------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blog_categories (
        blog_id INTEGER,
        category_id INTEGER,

        PRIMARY KEY (blog_id, category_id),

        FOREIGN KEY(blog_id)
        REFERENCES blogs(id)
        ON DELETE CASCADE,

        FOREIGN KEY(category_id)
        REFERENCES categories(id)
        ON DELETE CASCADE
    )
    """)

    conn.commit()
    conn.close()


# ==========================================
# Blog CRUD
# ==========================================

def add_blog(
    filename,
    original_title,
    display_title,
    created_at,
    word_count,
    image_count,
    evidence_count,
    runtime
):

    conn = get_connection()
    try:
      
      cursor = conn.cursor()

      cursor.execute(
          """
          SELECT id
          FROM blogs
          WHERE filename = ?
          """,
          (filename,)
      )

      existing = cursor.fetchone()

      if existing:

          cursor.execute(
              """
              UPDATE blogs
              SET
                  original_title = ?,
                  display_title = ?,
                  created_at = ?,
                  word_count = ?,
                  image_count = ?,
                  evidence_count = ?,
                  runtime = ?
              WHERE filename = ?
              """,
              (
                  original_title,
                  display_title,
                  created_at,
                  word_count,
                  image_count,
                  evidence_count,
                  runtime,
                  filename
              )
          )

      else:

          cursor.execute(
              """
              INSERT INTO blogs (
                  filename,
                  original_title,
                  display_title,
                  created_at,
                  word_count,
                  image_count,
                  evidence_count,
                  runtime
              )
              VALUES (?, ?, ?, ?, ?, ?, ?, ?)
              """,
              (
                  filename,
                  original_title,
                  display_title,
                  created_at,
                  word_count,
                  image_count,
                  evidence_count,
                  runtime
              )
          )

      conn.commit()
    finally:  
      conn.close()

def get_all_blogs():

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM blogs
    ORDER BY datetime(created_at) DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]


def get_blog(blog_id):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM blogs
    WHERE id = ?
    """, (blog_id,))

    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None


# ==========================================
# Pin / Unpin
# ==========================================

def toggle_pin(blog_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    UPDATE blogs
    SET pinned =
        CASE
            WHEN pinned = 1 THEN 0
            ELSE 1
        END
    WHERE id = ?
    """, (blog_id,))

    conn.commit()
    conn.close()


def get_pinned_blogs():

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM blogs
    WHERE pinned = 1
    ORDER BY datetime(created_at) DESC
    """)

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ==========================================
# Edit Sidebar Title
# ==========================================

def update_display_title(
    blog_id,
    new_title
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    UPDATE blogs
    SET display_title = ?
    WHERE id = ?
    """,
    (
        new_title,
        blog_id
    ))

    conn.commit()
    conn.close()


def set_pin_status(
    blog_id,
    pinned
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE blogs
        SET pinned = ?
        WHERE id = ?
        """,
        (
            pinned,
            blog_id
        )
    )

    conn.commit()
    conn.close()
# ==========================================
# Delete Blog
# ==========================================

def delete_blog(blog_id):

    conn = get_connection()
    try:
      cursor = conn.cursor()

      cursor.execute(
          """
          SELECT filename
          FROM blogs
          WHERE id = ?
          """,
          (blog_id,)
      )

      row = cursor.fetchone()

      if row:

          filename = row[0]

        # Delete markdown file
          md_path = (
              Path("blogs")
              / filename
          )

          try:
            if md_path.exists():
                md_path.unlink()
          except Exception as e:
              print(f"Delete error: {e}")

          # Delete JSON metadata file
          json_path = (
              Path("blog_data")
              / filename.replace(
                  ".md",
                  ".json"
              )
          )

          try:
            if json_path.exists():
                  json_path.unlink()
          except Exception as e:
            print(f"Delete error: {e}")

      cursor.execute(
          """
          DELETE FROM blogs
          WHERE id = ?
          """,
          (blog_id,)
      )

      conn.commit()
    finally:
      conn.close()


# ==========================================
# Search
# ==========================================

def search_blogs(query):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM blogs
    WHERE LOWER(display_title) LIKE LOWER(?)
    ORDER BY datetime(created_at) DESC
    """,
    (f"%{query}%",)
    )

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ==========================================
# Categories
# ==========================================

def create_category(name):

    name = name.strip()

    if not name:
        return False

    conn = get_connection()

    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR IGNORE INTO categories(name)
            VALUES (?)
            """,
            (name,)
        )

        conn.commit()

        return cursor.rowcount > 0

    finally:

        conn.close()


def delete_category(category_id):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM categories
    WHERE id = ?
    """, (category_id,))

    conn.commit()
    conn.close()


def get_categories():

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM categories
    ORDER BY name
    """)

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]


# ==========================================
# Blog -> Category
# ==========================================

def add_blog_to_category(
    blog_id,
    category_id
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR IGNORE INTO blog_categories
    VALUES (?, ?)
    """,
    (
        blog_id,
        category_id
    ))

    conn.commit()
    conn.close()


def remove_blog_from_category(
    blog_id,
    category_id
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM blog_categories
    WHERE blog_id = ?
    AND category_id = ?
    """,
    (
        blog_id,
        category_id
    ))

    conn.commit()
    conn.close()


def get_blogs_by_category(category_id):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT b.*
    FROM blogs b
    JOIN blog_categories bc
        ON b.id = bc.blog_id
    WHERE bc.category_id = ?
    ORDER BY b.created_at DESC
    """,
    (category_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]

def get_blog_by_filename(filename):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM blogs
    WHERE filename = ?
    """, (filename,))

    row = cursor.fetchone()

    conn.close()

    return dict(row) if row else None


def get_blog_categories(blog_id):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute("""
    SELECT c.*
    FROM categories c
    JOIN blog_categories bc
        ON c.id = bc.category_id
    WHERE bc.blog_id = ?
    ORDER BY c.name
    """, (blog_id,))

    rows = cursor.fetchall()

    conn.close()

    return [dict(r) for r in rows]
  
def rename_category(
    category_id,
    new_name
):
    new_name = new_name.strip()
    if not new_name:
        return False

    conn = get_connection()
    
    try:

        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE categories
            SET name = ?
            WHERE id = ?
            """,
            (
                new_name,
                category_id
            )
        )

        conn.commit()
        return cursor.rowcount > 0
    except sqlite3.IntegrityError:
       return False
    finally:
       conn.close()


def get_blog_category_ids(
    blog_id
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT category_id
        FROM blog_categories
        WHERE blog_id = ?
        """,
        (blog_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return [r[0] for r in rows]
  
# ==========================================
# Analytics
# ==========================================

def get_blog_statistics():

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_blogs,
            COALESCE(SUM(word_count),0) AS total_words,
            COALESCE(SUM(image_count),0) AS total_images,
            COALESCE(SUM(evidence_count),0) AS total_evidence,
            COALESCE(AVG(runtime),0) AS avg_runtime,
            SUM(
                CASE
                    WHEN pinned=1
                    THEN 1
                    ELSE 0
                END
            ) AS pinned
        FROM blogs
        """
    )

    row = cursor.fetchone()

    conn.close()

    return dict(row)
def get_all_blog_dataframe():

    conn = get_connection()

    df = pd.read_sql_query(

        """
        SELECT *
        FROM blogs
        ORDER BY datetime(created_at) DESC
        """,

        conn

    )

    conn.close()

    return df

def get_blog_growth():

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS blogs
        FROM blogs
        GROUP BY DATE(created_at)
        ORDER BY day
        """,
        conn,
    )

    conn.close()

    return df

def get_category_statistics():

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            c.name,
            COUNT(*) AS total
        FROM categories c
        JOIN blog_categories bc
            ON c.id = bc.category_id
        GROUP BY c.id
        ORDER BY total DESC
        """,
        conn,
    )

    conn.close()

    return df
  
#Monthly Summary
def get_month_statistics(year, month):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_blogs,
            COALESCE(SUM(word_count),0) AS total_words,
            COALESCE(SUM(image_count),0) AS total_images,
            COALESCE(SUM(evidence_count),0) AS total_evidence
        FROM blogs
        WHERE strftime('%Y', created_at)=?
        AND strftime('%m', created_at)=?
        """,
        (
            str(year),
            f"{month:02d}"
        )
    )

    row = cursor.fetchone()

    conn.close()

    return dict(row)
  
#Today's Blogs
def get_today_blog_count():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM blogs
        WHERE DATE(created_at)=DATE('now')
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count
  
#This Week
def get_week_blog_count():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM blogs
        WHERE DATE(created_at)
        >= DATE('now','-6 days')
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count
  
#This Month
def get_month_blog_count():

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM blogs
        WHERE strftime('%Y-%m',created_at)
        =
        strftime('%Y-%m','now')
        """
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count

def get_date_statistics(
    start_date,
    end_date
):

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_blogs,
            COALESCE(SUM(word_count), 0) AS total_words,
            COALESCE(SUM(image_count), 0) AS total_images,
            COALESCE(SUM(evidence_count), 0) AS total_evidence
        FROM blogs
        WHERE DATE(created_at)
        BETWEEN DATE(?)
        AND DATE(?)
        """,
        (
            start_date,
            end_date
        )
    )

    row = cursor.fetchone()

    conn.close()

    return dict(row)

def get_date_blog_dataframe(
    start_date,
    end_date
):

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT *
        FROM blogs
        WHERE DATE(created_at)
        BETWEEN DATE(?)
        AND DATE(?)
        ORDER BY datetime(created_at) DESC
        """,
        conn,
        params=(
            start_date,
            end_date
        )
    )

    conn.close()

    return df
def get_date_blog_growth(
    start_date,
    end_date
):

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS blogs
        FROM blogs
        WHERE DATE(created_at)
        BETWEEN DATE(?)
        AND DATE(?)
        GROUP BY DATE(created_at)
        ORDER BY day
        """,
        conn,
        params=(
            start_date,
            end_date
        )
    )

    conn.close()

    return df
def get_date_category_statistics(
    start_date,
    end_date
):

    conn = get_connection()

    df = pd.read_sql_query(
        """
        SELECT
            c.name,
            COUNT(*) AS total
        FROM categories c

        JOIN blog_categories bc
            ON c.id = bc.category_id

        JOIN blogs b
            ON b.id = bc.blog_id

        WHERE DATE(b.created_at)
        BETWEEN DATE(?)
        AND DATE(?)

        GROUP BY c.id

        ORDER BY total DESC
        """,
        conn,
        params=(
            start_date,
            end_date
        )
    )

    conn.close()

    return df


def get_available_blog_dates():

    conn = get_connection()

    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT

            MIN(
                DATE(created_at)
            ) AS first_blog,

            MAX(
                DATE(created_at)
            ) AS last_blog

        FROM blogs
        """
    )

    row = cursor.fetchone()

    conn.close()

    if row["first_blog"] is None:

        return {
            "first_blog": None,
            "last_blog": None,
        }

    return {
        "first_blog": row["first_blog"],
        "last_blog": row["last_blog"],
    }
    