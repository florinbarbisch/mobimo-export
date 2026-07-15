import os
import sys
import io
from pypdf import PdfReader, PdfWriter
from PIL import Image

def compress_pdf(input_path, output_path, max_dim=1200, jpeg_quality=50):
    if not os.path.exists(input_path):
        print(f"Error: Source file '{input_path}' not found.")
        return
        
    print(f"Opening source PDF: {input_path} ({os.path.getsize(input_path) / (1024*1024):.2f} MB)")
    reader = PdfReader(input_path)
    writer = PdfWriter()
    
    total_pages = len(reader.pages)
    print(f"Found {total_pages} pages. Processing and compressing images...")
    
    for idx, page in enumerate(reader.pages, 1):
        print(f"Processing page {idx}/{total_pages}...", end="\r")
        
        # Add the page to the writer first to get a writable PageObject reference
        writer_page = writer.add_page(page)
        
        # Access images on the writable page object
        if writer_page.images:
            for img_idx, img_file in enumerate(writer_page.images, 1):
                try:
                    # Load the image into PIL
                    pil_img = img_file.image
                    
                    # Convert RGBA/P to RGB if possible to allow JPEG compression (most photos are RGB)
                    if pil_img.mode in ("RGBA", "LA") or (pil_img.mode == "P" and "transparency" in pil_img.info):
                        # Keep PNG compression for transparent images
                        img_format = "PNG"
                    else:
                        if pil_img.mode != "RGB":
                            pil_img = pil_img.convert("RGB")
                        img_format = "JPEG"
                        
                    # Downscale image if it exceeds max_dim
                    width, height = pil_img.size
                    if width > max_dim or height > max_dim:
                        pil_img.thumbnail((max_dim, max_dim))
                    
                    # Compress the image in-memory
                    img_byte_arr = io.BytesIO()
                    if img_format == "JPEG":
                        pil_img.save(img_byte_arr, format="JPEG", quality=jpeg_quality, optimize=True)
                    else:
                        pil_img.save(img_byte_arr, format="PNG", optimize=True)
                        
                    img_byte_arr.seek(0)
                    compressed_pil_img = Image.open(img_byte_arr)
                    
                    # Replace the image in the PDF page
                    img_file.replace(compressed_pil_img)
                except Exception as e:
                    # Print on a new line to not overwrite the progress bar
                    print(f"\n[Warning] Page {idx}, Image {img_idx} compression failed: {e}")
                    
        # Apply standard content stream compression (lossless deflate for text/layouts)
        try:
            writer_page.compress_content_streams()
        except Exception:
            pass
        
    print("\nWriting compressed PDF...")
    # Apply global writer compression settings to remove duplicate objects
    try:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except Exception:
        pass
        
    with open(output_path, "wb") as f_out:
        writer.write(f_out)
        
    original_size = os.path.getsize(input_path) / (1024*1024)
    compressed_size = os.path.getsize(output_path) / (1024*1024)
    reduction = (1 - (compressed_size / original_size)) * 100
    
    print("=" * 50)
    print("COMPRESSION SUCCESSFUL!")
    print(f"Original PDF size:   {original_size:.2f} MB")
    print(f"Compressed PDF size: {compressed_size:.2f} MB")
    print(f"Size Reduction:      {reduction:.1f}%")
    print(f"Output saved to:     {output_path}")
    print("=" * 50)

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_pdf = os.path.join(script_dir, "deficiencies_report.pdf")
    output_pdf = os.path.join(script_dir, "deficiencies_report_compressed.pdf")
    
    compress_pdf(input_pdf, output_pdf)
