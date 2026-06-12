#!/usr/bin/env python3
"""Create a test PDF with a YouTube URL for Test Case 4."""

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

pdf_path = "temp_uploads/test_youtube_pdf.pdf"

c = canvas.Canvas(pdf_path, pagesize=letter)
width, height = letter

# Add title
c.setFont("Helvetica-Bold", 16)
c.drawString(inch, height - inch, "Test Document with YouTube Link")

# Add some content
c.setFont("Helvetica", 12)
c.drawString(inch, height - 1.5*inch, "This is a test PDF document that contains a YouTube URL.")
c.drawString(inch, height - 1.8*inch, "Please extract and summarize the content from this video:")

# Add the YouTube URL
c.setFont("Helvetica-Bold", 11)
c.setFillColorRGB(0, 0, 1)  # Blue text for URL
c.drawString(inch, height - 2.3*inch, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# Add more content
c.setFont("Helvetica", 12)
c.setFillColorRGB(0, 0, 0)  # Back to black
c.drawString(inch, height - 2.8*inch, "Additional instructions:")
c.drawString(inch, height - 3.1*inch, "1. The video contains interesting content about productivity.")
c.drawString(inch, height - 3.4*inch, "2. Please provide a one-line summary, 3 bullet points, and a 5-sentence summary.")
c.drawString(inch, height - 3.7*inch, "3. Do not include any other information beyond the video summary.")

c.save()
print(f"✅ Test PDF created at: {pdf_path}")
