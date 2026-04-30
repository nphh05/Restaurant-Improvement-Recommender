import asyncio
import random
import os
import re
import pandas as pd
from playwright.async_api import async_playwright

# ==========================================
# CẤU HÌNH GIAI ĐOẠN 2
# ==========================================
INPUT_FILE = "danh_sach_link.txt"     
START_INDEX = 0
END_INDEX = 1

MAX_TOTAL_REVIEWS = 20          
MIN_LENGTH = 30                       
MAX_LENGTH = 1000                     

SUMMARY_FILE = "thong_ke_nha_hang1.csv"   
REVIEWS_FILE = "du_lieu_reviews_chi_tiet.csv" # Đổi tên file để phân biệt   

async def human_delay(a=1.2, b=2.5):
    await asyncio.sleep(random.uniform(a, b))

async def change_sort(page, sort_type="Lowest"):
    try:
        sort_btn = await page.wait_for_selector(
            "button:has-text('Phù hợp nhất'), button:has-text('Mới nhất'), button:has-text('Xếp hạng thấp nhất'), button:has-text('Xếp hạng cao nhất'), button[aria-label*='Sắp xếp']", 
            timeout=5000
        )
        await sort_btn.scroll_into_view_if_needed()
        await sort_btn.click()
        await human_delay(1.5, 2.5) 
        
        if sort_type == "Lowest":
            option_locator = page.locator('div[role="menuitemradio"]:has-text("Xếp hạng thấp nhất")')
        else:
            option_locator = page.locator('div[role="menuitemradio"]:has-text("Xếp hạng cao nhất")')
            
        await option_locator.wait_for(state="visible", timeout=5000)
        await option_locator.evaluate("node => node.click()")
        await human_delay(3, 5) 
        return True
    except Exception as e:
        print(f"Lỗi đổi bộ lọc: {e}") 
        return False

# --- HÀM HỖ TRỢ BÓC TÁCH DỮ LIỆU ---
def extract_field(pattern, text):
    """Dùng regex để tìm chuỗi, nếu không có trả về chuỗi rỗng"""
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""

async def scrape_current_view(page, current_reviews_dict, limit):
    """Cào cho đến khi TỔNG giỏ reviews đạt 'limit'."""
    last_count = 0
    same_count = 0
    
    try:
        await page.wait_for_selector("div.jftiEf", timeout=7000)
    except: return 0

    start_count = len(current_reviews_dict)

    while len(current_reviews_dict) < limit:
        blocks = await page.query_selector_all("div.jftiEf")
        for b in blocks:
            try:
                # 1. LẤY SỐ SAO TỔNG QUAN
                star_rating = ""
                star_el = await b.query_selector("span[role='img']")
                if star_el:
                    aria_label = await star_el.get_attribute("aria-label")
                    if aria_label:
                        match = re.search(r'\d+', aria_label)
                        if match: star_rating = match.group()

                # 2. BẤM NÚT DỊCH NẾU CÓ
                translate_btn = await b.query_selector("button:has-text('Dịch'), button:has-text('Translate')")
                if translate_btn:
                    btn_text = await translate_btn.inner_text()
                    if "bản gốc" not in btn_text.lower() and "original" not in btn_text.lower():
                        try:
                            await translate_btn.click()
                            await human_delay(0.8, 1.5) 
                        except: pass

                # 3. MỞ RỘNG TEXT (XEM THÊM)
                review_container = await b.query_selector("div.MyEned")
                if not review_container: continue

                more_btn = await review_container.query_selector("button:has-text('Xem thêm'), button:has-text('More')")
                if more_btn:
                    try:
                        await more_btn.click()
                        await human_delay(0.4, 0.7)
                    except: pass

                # 4. LẤY NỘI DUNG VÀ CÁC TRƯỜNG THÔNG TIN MỚI
                text_el = await review_container.query_selector("span.wiI7pd")
                if text_el:
                    review_text = await text_el.inner_text()
                    
                    if MIN_LENGTH <= len(review_text) <= MAX_LENGTH:
                        clean_text = review_text.replace('\n', ' ').strip()
                        
                        # -- TRÍCH XUẤT CÁC TRƯỜNG BỔ SUNG --
                        # Lấy toàn bộ text hiển thị trong khối review này
                        full_block_text = await b.inner_text()
                        
                        extra_data = {
                            "overall_stars": star_rating,
                            "food_rating": extract_field(r'Đồ ăn:\s*(\d+)', full_block_text),
                            "service_rating": extract_field(r'Dịch vụ:\s*(\d+)', full_block_text),
                            "atmosphere_rating": extract_field(r'Bầu không khí:\s*(\d+)', full_block_text),
                            "meal_type": extract_field(r'Loại hình bữa ăn\n([^\n]+)', full_block_text),
                            "price_per_person": extract_field(r'Giá mỗi người\n([^\n]+)', full_block_text),
                            "reservation": extract_field(r'Đặt chỗ\n([^\n]+)', full_block_text),
                            "noise_level": extract_field(r'Độ ồn\n([^\n]+)', full_block_text)
                        }
                        
                        # Lưu vào Dict: key là text, value là dict chứa các thuộc tính
                        current_reviews_dict[clean_text] = extra_data
                        
                        if len(current_reviews_dict) >= limit: break
            except: continue

        if len(current_reviews_dict) >= limit: break

        # CUỘN TRANG
        if blocks:
            await blocks[-1].hover() 
        await page.mouse.wheel(0, 1500)
        await human_delay(2, 3)

        current_on_screen = len(await page.query_selector_all("div.jftiEf"))
        if current_on_screen == last_count:
            same_count += 1
            if same_count > 3: break
        else: same_count = 0
        last_count = current_on_screen
    
    return len(current_reviews_dict) - start_count

async def run():
    if not os.path.exists(INPUT_FILE): return
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        urls_list = [line.strip() for line in f if line.strip()]
    ca_hien_tai = urls_list[START_INDEX:END_INDEX]
    
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=f"user_data_reviews_{START_INDEX}",
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            locale="vi-VN"
        )
        page = await browser.new_page()

        for idx, url in enumerate(ca_hien_tai):
            print(f"\n[{idx+1}/{len(ca_hien_tai)}] Quán số {START_INDEX + idx}")
            try:
                await page.goto(url)
                await human_delay(4, 6)
                
                name_el = await page.wait_for_selector("h1", timeout=5000)
                restaurant_name = await name_el.inner_text()
                
                btn = await page.wait_for_selector("//button[contains(., 'Bài đánh giá') or contains(., 'Reviews')]", timeout=5000)
                await btn.click()
                await human_delay(2, 4)
                
                final_reviews_dict = {}

                # CHIA 50/50 XẤU VÀ TỐT
                HALF_LIMIT = MAX_TOTAL_REVIEWS // 2

                print(f"⏬ Đang gom {HALF_LIMIT} đánh giá Xấu...")
                bad_count = 0
                if await change_sort(page, "Lowest"):
                    bad_count = await scrape_current_view(page, final_reviews_dict, HALF_LIMIT)
                
                good_count = 0
                if len(final_reviews_dict) < MAX_TOTAL_REVIEWS:
                    remaining = MAX_TOTAL_REVIEWS - len(final_reviews_dict)
                    print(f"🔄 Đã có {len(final_reviews_dict)} Xấu, đang lấy thêm {remaining} Tốt cho đủ {MAX_TOTAL_REVIEWS}...")
                    if await change_sort(page, "Highest"):
                        good_count = await scrape_current_view(page, final_reviews_dict, MAX_TOTAL_REVIEWS)

                print(f"📊 Kết quả: {bad_count} Xấu, {good_count} Tốt. Tổng: {len(final_reviews_dict)}")

                if final_reviews_dict:
                    # 1. Thống kê
                    summary_df = pd.DataFrame([{"restaurant_name": restaurant_name, "bad": bad_count, "good": good_count, "total": len(final_reviews_dict)}])
                    summary_df.to_csv(SUMMARY_FILE, mode='a', index=False, header=not os.path.isfile(SUMMARY_FILE), encoding="utf-8-sig")

                    # 2. Lưu chi tiết ra CSV
                    reviews_list = []
                    for text, data in final_reviews_dict.items():
                        # Gom dữ liệu thành 1 hàng
                        row_data = {
                            "restaurant_name": restaurant_name,
                            "overall_stars": data["overall_stars"],
                            "food_rating": data["food_rating"],
                            "service_rating": data["service_rating"],
                            "atmosphere_rating": data["atmosphere_rating"],
                            "meal_type": data["meal_type"],
                            "price_per_person": data["price_per_person"],
                            "reservation": data["reservation"],
                            "noise_level": data["noise_level"],
                            "review_text": text
                        }
                        reviews_list.append(row_data)
                    
                    df_reviews = pd.DataFrame(reviews_list)
                    df_reviews.to_csv(REVIEWS_FILE, mode='a', index=False, header=not os.path.isfile(REVIEWS_FILE), encoding="utf-8-sig")
                    
                    print(f"💾 Đã lưu xong dữ liệu chi tiết vào {REVIEWS_FILE}.")

            except Exception as e:
                print(f"❌ Lỗi: {e}")
                continue
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())