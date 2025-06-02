
import time
import base64
from google import genai
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
import yt_dlp
import os
import assemblyai as aai
import httpx
from .models import BlogPost


# Create your views here.
@login_required
def index(request):
    return render(request, 'index.html')

@csrf_exempt
def generate_blog(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            yt_link = data['link']
            user_prompt = data['prompt']

            title = yt_title(yt_link)
            transcription = get_transcription(yt_link)

            if not transcription:
                return JsonResponse({'error': "Failed to get transcript"}, status=500)

            blog_content = generate_blog_from_transcription(transcription, user_prompt)

            if not blog_content:
                return JsonResponse({'error': "Failed to generate blog article"}, status=500)

            new_blog_article = BlogPost.objects.create(
                user=request.user,
                youtube_title=title,
                youtube_link=yt_link,
                generated_content=blog_content,
            )
            new_blog_article.save()

            return JsonResponse({'content': blog_content})

        except Exception as e:
            print("Error in generate_blog:", str(e))  # This prints error in terminal
            return JsonResponse({'error': 'Internal Server Error'}, status=500)

    return JsonResponse({'error': 'Invalid request method'}, status=405)


def create_cookies_file():
    cookies_b64 = os.getenv("YT_COOKIES_BASE64")
    if not cookies_b64:
        raise Exception("Environment variable YT_COOKIES_BASE64 is missing")

    cookie_path = os.path.join(settings.BASE_DIR, 'cookies.txt')
    with open(cookie_path, "wb") as f:
        f.write(base64.b64decode(cookies_b64))
    return cookie_path

def remove_cookie_file(cookie_path):
    try:
        os.remove(cookie_path)
    except Exception:
        pass


def yt_title(link):
    ydl_opts = {
        'quiet': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=False)
        return info_dict.get('title', 'No title found')

# def download_audio(link):
#     ydl_opts = {
#         'format': 'bestaudio/best',
#         'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(title)s.%(ext)s'),
#         'cookiefile': os.path.join(settings.BASE_DIR, 'cookies.txt'),
#         'postprocessors': [{
#             'key': 'FFmpegExtractAudio',
#             'preferredcodec': 'mp3',
#             'preferredquality': '192',
#         }],
#     }
#     with yt_dlp.YoutubeDL(ydl_opts) as ydl:
#         info_dict = ydl.extract_info(link, download=True)
#         audio_file = ydl.prepare_filename(info_dict)
#         base, ext = os.path.splitext(audio_file)
#         new_file = base + '.mp3'
#         if os.path.exists(new_file):
#             return new_file
#         else:
#             raise Exception("Failed to download audio")
        

def download_audio(link):
    # --- Path for cookies.txt ---
    # settings.BASE_DIR points to 'MINI_PROJECT/youtube-ai-transcript-generator/ai_blog_app/'
    # We want to go up one level to 'youtube-ai-transcript-generator/'
    # then into the 'config' folder, and finally to 'cookies.txt'.
    
    # Path to the 'youtube-ai-transcript-generator' directory (your project root)
    project_root = os.path.dirname(settings.BASE_DIR)
    
    # Construct the full path to cookies.txt
    cookies_file_path = os.path.join(project_root, 'config', 'cookies.txt')

    # --- Crucial Check: Verify cookie file exists ---
    if not os.path.exists(cookies_file_path):
        raise FileNotFoundError(f"Cookies file not found at expected path: {cookies_file_path}")

    # --- yt-dlp Options ---
    ydl_opts = {
        'format': 'bestaudio/best',
        # Ensure MEDIA_ROOT is correctly configured in your Django settings for downloads
        'outtmpl': os.path.join(settings.MEDIA_ROOT, '%(title)s.%(ext)s'),
        
        # This is the corrected path for your cookies file
        'cookiefile': cookies_file_path, 
        
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'noplaylist': True,  # Ensures only single video is processed if a playlist URL is given
        'nocheckcertificate': True, # Often helpful in cloud environments
        'quiet': True,       # Suppress most console output from yt-dlp
        'no_warnings': True, # Suppress warnings
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Create the MEDIA_ROOT directory if it doesn't exist
            # This is good practice to ensure the download path is ready
            os.makedirs(settings.MEDIA_ROOT, exist_ok=True)

            info_dict = ydl.extract_info(link, download=True)
            
            # yt-dlp's prepare_filename is for the original download path, 
            # not necessarily the final post-processed MP3.
            # We can construct the final MP3 path more reliably.
            # info_dict contains 'id' and 'title' which are useful for filenames
            video_id = info_dict.get('id')
            video_title_sanitized = ydl.sanitize_filename(info_dict.get('title', video_id)) # Sanitize for filename safety

            # Construct the expected final MP3 file path
            # Assuming 'outtmpl' creates a file like 'MEDIA_ROOT/Video Title.ext'
            # and then postprocessor converts it to 'MEDIA_ROOT/Video Title.mp3'
            final_audio_file_path = os.path.join(settings.MEDIA_ROOT, f"{video_title_sanitized}.mp3")

            if os.path.exists(final_audio_file_path):
                print(f"Successfully downloaded and processed audio to: {final_audio_file_path}")
                return final_audio_file_path
            else:
                # If the file doesn't exist here, something went wrong with download or post-processing
                raise Exception(f"Failed to find final audio file at {final_audio_file_path} after download.")

    except yt_dlp.DownloadError as e:
        print(f"yt-dlp Download Error: {e}")
        # This is where you'll likely catch the 'Sign in to confirm' bot error
        raise Exception(f"Video download failed: {e}") 
    except Exception as e:
        print(f"An unexpected error occurred during audio download: {e}")
        raise Exception(f"An unexpected error occurred: {e}")



def get_transcription(link):
    audio_file = download_audio(link)
    aai.settings.api_key = settings.ASSEMBLYAI_API_KEY

    transcriber = aai.Transcriber()
    retries = 3
    for i in range(retries):
        try:
            transcript = transcriber.transcribe(audio_file)
            return transcript.text
        except httpx.ReadTimeout:
            if i < retries - 1:
                time.sleep(2)  # wait before retrying
                continue
            else:
                raise
    return None



def generate_blog_from_transcription(transcription, user_prompt):

    client = genai.Client(api_key=settings.GOOGLE_API_KEY)
    prompt = f"""
        {user_prompt}
        here is the Transcript:
        {transcription}
    """

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt  # ✅ pass as plain string
    )

    return response.text



def blog_list(request):
    blog_articles = BlogPost.objects.filter(user=request.user)
    return render(request, "all-blogs.html", {'blog_articles': blog_articles})

def blog_details(request, pk):
    blog_article_detail = BlogPost.objects.get(id=pk)
    if request.user == blog_article_detail.user:
        return render(request, 'blog-details.html', {'blog_article_detail': blog_article_detail})
    else:
        return redirect('/')
    
def user_login(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('/')
        else:
            error_message = "Invalid username or password"
            return render(request, 'login.html', {'error_message': error_message})
        
    return render(request, 'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                user.save()
                login(request, user)
                return redirect('/')
            except:
                error_message = 'Error creating account'
                return render(request, 'signup.html', {'error_message':error_message})
        else:
            error_message = 'Password do not match'
            return render(request, 'signup.html', {'error_message':error_message})
        
    return render(request, 'signup.html')

def user_logout(request):
    logout(request)
    return redirect('/')
